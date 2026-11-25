/* =============================================================================
 * leo_websocket.js — Manager central des connexions WebSocket Lyneci
 * =============================================================================
 *
 * Caractéristiques :
 *   - Backoff exponentiel (1s, 2s, 4s, 8s, ..., 60s max)
 *   - État de connexion partagé propagé à tous les badges
 *     (data-leo-connection-badge sur la page)
 *   - Vérification du champ payload.version pour ignorer les versions inconnues
 *   - Heartbeat client : envoie {action: "ping"} toutes les 25s
 *   - Buffer interne en cas de perte transitoire (max 100 messages)
 *   - API publique :
 *        const conn = LeoWS.connect(url, { onMessage, name, expectedEvent });
 *        conn.send({...});
 *        conn.close();
 *        LeoWS.state();        // "online" | "reconnecting" | "offline"
 *        LeoWS.onStateChange(cb);
 *
 * Sécurité : ce module n'écrit JAMAIS dans le DOM, il délègue tout au caller
 * via onMessage. C'est le caller qui choisit textContent / safe rendering.
 * ============================================================================= */

(function (global) {
  "use strict";

  const PROTOCOL_VERSION = 1;
  const MAX_BACKOFF_MS = 60_000;
  const PING_INTERVAL_MS = 25_000;
  const BUFFER_MAX_SIZE = 500;          // Augmenté de 100 → 500 (handle 30s de downtime)
  const DEDUP_WINDOW_MS  = 200;         // Fenêtre de déduplication des messages identiques
  const RECONNECT_JITTER = 0.2;         // ±20% jitter pour éviter thundering herd

  // État global partagé entre toutes les connexions
  let connections = new Map();              // name → connection wrapper
  let stateListeners = new Set();
  let currentState = "online";              // "online" | "reconnecting" | "offline"

  function setGlobalState(newState) {
    if (newState === currentState) return;
    currentState = newState;
    propagateBadgeState(newState);
    stateListeners.forEach((cb) => {
      try { cb(newState); } catch (_) { /* noop */ }
    });
  }

  function recomputeGlobalState() {
    if (connections.size === 0) {
      setGlobalState("online");
      return;
    }
    let anyReconnecting = false;
    let allOffline = true;
    connections.forEach((c) => {
      if (c.state === "open") allOffline = false;
      if (c.state === "reconnecting") anyReconnecting = true;
      if (c.state !== "offline") allOffline = false;
    });
    if (allOffline) setGlobalState("offline");
    else if (anyReconnecting) setGlobalState("reconnecting");
    else setGlobalState("online");
  }

  function propagateBadgeState(state) {
    const badges = document.querySelectorAll("[data-leo-connection-badge]");
    badges.forEach((el) => {
      el.setAttribute("data-state", state);
      const text = el.querySelector(".leo-connection-text");
      if (text) {
        if (state === "online") text.textContent = "Live";
        else if (state === "reconnecting") text.textContent = "Reconnexion…";
        else text.textContent = "Hors-ligne";
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Connection wrapper
  // ---------------------------------------------------------------------------
  function Connection(url, options) {
    this.url = url;
    this.opts = Object.assign(
      {
        name: url,                  // pour logging
        expectedEvent: null,         // si défini, filtre les messages
        onMessage: null,             // (data, payload) => void
        onOpen: null,
        onClose: null,
      },
      options || {}
    );
    this.ws = null;
    this.state = "idle";             // idle | connecting | open | reconnecting | offline | closed
    this.attempt = 0;
    this.shouldReconnect = true;
    this.pingTimer = null;
    this.reconnectTimer = null;
    this.outbox = [];                // buffer pour messages envoyés avant connexion
    this._dedupCache = new Map();    // msg_hash → timestamp, déduplication
  }

  Connection.prototype.connect = function () {
    if (this.state === "closed") return;
    this.state = "connecting";

    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (err) {
      console.warn("[LeoWS] cannot create socket", this.opts.name, err);
      this._scheduleReconnect();
      return;
    }

    this.ws = ws;

    ws.onopen = () => {
      this.state = "open";
      this.attempt = 0;
      console.log("[LeoWS] open", this.opts.name);
      this._startPing();
      this._flushOutbox();
      recomputeGlobalState();
      if (typeof this.opts.onOpen === "function") {
        try { this.opts.onOpen(); } catch (_) {}
      }
    };

    ws.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (_) {
        return; // ignore les frames non-JSON
      }

      // Filtrage par event attendu
      if (this.opts.expectedEvent && data.event && data.event !== this.opts.expectedEvent) {
        return;
      }

      // Vérification de version : on ignore les payloads de version supérieure
      const payload = data.payload || {};
      const v = payload.version;
      if (typeof v === "number" && v > PROTOCOL_VERSION) {
        console.warn(
          "[LeoWS] payload version",
          v,
          "> client",
          PROTOCOL_VERSION,
          "→ ignoré",
          this.opts.name
        );
        return;
      }

      // Déduplication : ignore les messages identiques reçus en rafale
      const dedupKey = data.event + "|" + (data.id || "") + "|" + JSON.stringify(payload).slice(0, 120);
      const now = Date.now();
      const lastSeen = this._dedupCache.get(dedupKey);
      if (lastSeen && now - lastSeen < DEDUP_WINDOW_MS) {
        return; // doublon ignoré
      }
      this._dedupCache.set(dedupKey, now);
      // Nettoyer le cache périodiquement (evict les entrées > 2s)
      if (this._dedupCache.size > 50) {
        const cutoff = now - 2000;
        this._dedupCache.forEach((ts, k) => { if (ts < cutoff) this._dedupCache.delete(k); });
      }

      if (typeof this.opts.onMessage === "function") {
        try {
          this.opts.onMessage(data, payload);
        } catch (err) {
          console.warn("[LeoWS] onMessage threw", err);
        }
      }
    };

    ws.onerror = () => {
      // Ne change pas l'état immédiatement — onclose suivra et on y gère le retry
    };

    ws.onclose = () => {
      this._stopPing();
      if (typeof this.opts.onClose === "function") {
        try { this.opts.onClose(); } catch (_) {}
      }
      if (this.shouldReconnect && this.state !== "closed") {
        this._scheduleReconnect();
      } else {
        this.state = "closed";
        recomputeGlobalState();
      }
    };
  };

  Connection.prototype._scheduleReconnect = function () {
    this.state = "reconnecting";
    recomputeGlobalState();
    this.attempt += 1;
    const base = Math.min(1000 * Math.pow(2, this.attempt - 1), MAX_BACKOFF_MS);
    // Jitter ±20% pour éviter que tous les clients reconnectent au même instant
    const jitter = base * RECONNECT_JITTER * (Math.random() * 2 - 1);
    const delay = Math.max(500, Math.round(base + jitter));
    console.log("[LeoWS] reconnect", this.opts.name, "in", delay, "ms (attempt", this.attempt, ")");

    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      if (this.shouldReconnect) this.connect();
    }, delay);
  };

  Connection.prototype._startPing = function () {
    this._stopPing();
    this.pingTimer = setInterval(() => {
      try {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: "ping" }));
        }
      } catch (_) { /* noop */ }
    }, PING_INTERVAL_MS);
  };

  Connection.prototype._stopPing = function () {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  };

  Connection.prototype._flushOutbox = function () {
    while (this.outbox.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
      const msg = this.outbox.shift();
      try { this.ws.send(JSON.stringify(msg)); } catch (_) { break; }
    }
  };

  Connection.prototype.send = function (msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try { this.ws.send(JSON.stringify(msg)); return true; } catch (_) {}
    }
    if (this.outbox.length < BUFFER_MAX_SIZE) this.outbox.push(msg);
    return false;
  };

  Connection.prototype.close = function () {
    this.shouldReconnect = false;
    this.state = "closed";
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this._stopPing();
    try { this.ws && this.ws.close(); } catch (_) {}
    connections.delete(this.opts.name);
    recomputeGlobalState();
  };

  // ---------------------------------------------------------------------------
  // API publique
  // ---------------------------------------------------------------------------
  const LeoWS = {
    connect: function (url, options) {
      const name = (options && options.name) || url;

      // Réutilise une connexion vivante vers la même URL (cas fréquent :
      // double init Alpine). Fermer une socket encore en CONNECTING pour la
      // recréer aussitôt déclenche "WebSocket is closed before the
      // connection is established" — on met juste à jour les callbacks.
      const existing = connections.get(name);
      if (existing && existing.url === url && existing.state !== "closed") {
        if (options) Object.assign(existing.opts, options);
        return existing;
      }
      if (existing) existing.close();

      const conn = new Connection(url, options);
      connections.set(name, conn);
      conn.connect();
      return conn;
    },

    closeAll: function () {
      connections.forEach((c) => c.close());
      connections.clear();
      recomputeGlobalState();
    },

    state: function () {
      return currentState;
    },

    onStateChange: function (cb) {
      stateListeners.add(cb);
      return () => stateListeners.delete(cb);
    },

    PROTOCOL_VERSION: PROTOCOL_VERSION,
  };

  global.LeoWS = LeoWS;
})(window);
