/**
 * leo_assistant.js — Panel IA conversationnel LeoAI
 * ==================================================
 *
 * Gestion complète du panel :
 *  - WebSocket streaming (DeepSeek / Claude)
 *  - Rendu markdown léger des réponses
 *  - Cartes d'actions avec flux de confirmation
 *  - Boutons "Expliquer" sur les cartes d'opportunités
 *  - Contexte page courante injecté automatiquement
 *
 * Usage global :
 *   LeoAssistant.open()
 *   LeoAssistant.sendMessage("Analyse R_75")
 *   LeoAssistant.explainOpportunity(42, "BUY", "R_75", "15m")
 */

(function (window) {
  "use strict";

  // ── Config ────────────────────────────────────────────────────────────────

  const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/assistant/chat/`;
  const RECONNECT_DELAY_BASE = 2000;
  const RECONNECT_DELAY_MAX = 30000;
  const WELCOME_MSG = "Bonjour ! Je suis **LeoAI**, votre copilote de trading.\n\nJe peux :\n• Analyser vos opportunités et positions\n• Calculer votre exposition et taille de position\n• Expliquer les scores et décisions du moteur IA\n• Vous avertir sur les risques\n\nComment puis-je vous aider ?";

  // ── État ──────────────────────────────────────────────────────────────────

  const state = {
    ws: null,
    isOpen: false,
    isConnected: false,
    isThinking: false,
    sessionId: null,
    currentMsgId: null,
    streamComplete: false,  // ← true quand le message "done" a été reçu pour la bulle en cours
    reconnectAttempts: 0,
    totalCostUsd: 0,
    pendingActionsCount: 0,
    historyLoaded: false,   // ← true après le premier rendu de l'historique
    clientContext: {
      page: document.body.dataset.leoPage || "dashboard",
    },
  };

  // ── Éléments DOM ─────────────────────────────────────────────────────────

  const $ = (id) => document.getElementById(id);
  let els = {};

  function initEls() {
    els = {
      panel:         $("leo-ai-panel"),
      overlay:       $("leo-ai-overlay"),
      toggle:        $("leo-ai-toggle"),
      closeBtn:      $("leo-ai-close-btn"),
      clearBtn:      $("leo-ai-clear-btn"),
      messages:      $("leo-ai-messages"),
      input:         $("leo-ai-input"),
      sendBtn:       $("leo-ai-send-btn"),
      statusDot:     $("leo-ai-status-dot"),
      statusText:    $("leo-ai-status-text"),
      badge:         $("leo-ai-badge"),
      pagePill:      $("leo-ai-page-pill"),
      pageLabel:     $("leo-ai-page-label"),
      portfolioPill: $("leo-ai-portfolio-pill"),
      portfolioLabel:$("leo-ai-portfolio-label"),
      ksBanner:      $("leo-ai-ks-banner"),
      costEl:        $("leo-ai-cost"),
      suggestions:   $("leo-ai-suggestions"),
    };
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────

  function connect() {
    if (state.ws && state.ws.readyState < 2) return;

    state.ws = new WebSocket(WS_URL);

    state.ws.onopen = () => {
      state.isConnected = true;
      state.reconnectAttempts = 0;
      setStatus("connected", "LeoAI connecté");
    };

    state.ws.onmessage = (event) => {
      try {
        handleServerMessage(JSON.parse(event.data));
      } catch (e) {
        console.warn("[LeoAI] parse error", e);
      }
    };

    state.ws.onclose = (event) => {
      state.isConnected = false;
      setStatus("offline", "Reconnexion…");

      if (event.code === 4401) {
        setStatus("offline", "Non authentifié");
        return;
      }

      // Si un stream était en cours ET n'a pas reçu son "done" → vraie interruption
      if (state.currentMsgId && !state.streamComplete) {
        const bubble = document.querySelector(`[data-msg-id="${state.currentMsgId}"]`);
        if (bubble && !bubble.dataset.raw) {
          // Bulle vide (stream pas encore commencé) → supprimer le thinking + la bulle
          removeThinking();
          const wrapper = bubble.closest(".leo-ai-msg");
          if (wrapper) wrapper.remove();
        } else if (bubble) {
          // Bulle partiellement remplie → nettoyer les marqueurs d'action et noter l'interruption
          const cleaned = stripActionMarkers(bubble.dataset.raw || "");
          bubble.dataset.raw = cleaned + "\n\n*[réponse interrompue — reconnexion en cours…]*";
          bubble.innerHTML = renderMarkdown(bubble.dataset.raw);
        }
        state.isThinking = false;
        setSendDisabled(false);
      }

      // Réinitialiser l'état du stream dans tous les cas
      state.currentMsgId = null;
      state.streamComplete = false;

      removeThinking();

      const delay = Math.min(
        RECONNECT_DELAY_BASE * Math.pow(1.5, state.reconnectAttempts),
        RECONNECT_DELAY_MAX
      );
      state.reconnectAttempts++;
      setTimeout(connect, delay + Math.random() * 1000);
    };

    state.ws.onerror = () => {
      setStatus("offline", "Erreur WS");
    };
  }

  function send(payload) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  // ── Gestion des messages serveur ─────────────────────────────────────────

  function handleServerMessage(data) {
    switch (data.type) {

      case "session":
        state.sessionId = data.session_id;
        // N'affiche l'historique que lors de la PREMIÈRE connexion.
        // Sur les reconnexions suivantes, on conserve le DOM en place pour
        // éviter que les messages streamés en cours ou déjà affichés disparaissent.
        if (!state.historyLoaded) {
          state.historyLoaded = true;
          if (data.history && data.history.length) {
            renderHistory(data.history);
          } else {
            appendWelcome();
          }
        }
        break;

      case "thinking":
        state.isThinking = true;
        setSendDisabled(true);
        appendThinking();
        break;

      case "start":
        state.currentMsgId = data.id;
        state.streamComplete = false;
        removeThinking();
        // Crée la bulle vide qui sera remplie par les chunks
        appendAssistantBubble(data.id, "");
        break;

      case "chunk":
        state.isThinking = false;
        appendChunk(data.id, data.text);
        break;

      case "done":
        state.isThinking = false;
        state.streamComplete = true;
        setSendDisabled(false);
        state.currentMsgId = null;

        // Remplace le texte brut (avec marqueurs <<<ACTION>>>) par le texte
        // épuré fourni par le serveur après extraction des blocs d'action.
        // Fallback : strip client-side si clean_content absent (ancienne version).
        {
          const bubble = document.querySelector(`[data-msg-id="${data.id}"]`);
          if (bubble) {
            const finalText = data.clean_content !== undefined
              ? data.clean_content
              : stripActionMarkers(bubble.dataset.raw || "");
            bubble.dataset.raw = finalText;
            bubble.innerHTML = renderMarkdown(finalText);
          }
        }

        if (data.actions && data.actions.length) {
          renderActionCards(data.id, data.actions);
          updateBadge(data.actions.length);
        }

        if (data.meta && data.meta.has_kill_switch) {
          showKillSwitchBanner(true);
        }
        scrollToBottom();
        break;

      case "action_update":
        updateActionCard(data.action_id, data.status, data.result);
        if (data.status === "CONFIRMED" && data.result && data.result.redirect === "draft_order") {
          openDraftOrderModal(data.result.params);
        }
        break;

      case "history":
        if (data.messages) renderHistory(data.messages);
        break;

      case "error":
        removeThinking();
        setSendDisabled(false);
        appendErrorMsg(data.message || "Erreur inconnue");
        break;
    }
  }

  // ── Rendu des messages ────────────────────────────────────────────────────

  function renderHistory(messages) {
    if (!els.messages) return;
    els.messages.innerHTML = "";

    if (!messages.length) {
      appendWelcome();
      return;
    }

    messages.forEach((m) => {
      if (m.role === "USER") {
        appendUserBubble(m.content, m.created_at);
      } else if (m.role === "ASSISTANT") {
        appendAssistantBubble(m.id, m.content, m.created_at);
        if (m.actions && m.actions.length) {
          renderActionCards(m.id, m.actions, true);
        }
      }
    });
    scrollToBottom();
  }

  function appendWelcome() {
    appendAssistantBubble("welcome", WELCOME_MSG);
  }

  function appendUserBubble(text, ts) {
    const div = document.createElement("div");
    div.className = "leo-ai-msg leo-ai-msg-user";
    div.innerHTML = `
      <div class="leo-ai-bubble">${escapeHtml(text)}</div>
      <div class="leo-ai-ts">${formatTs(ts)}</div>
    `;
    els.messages.appendChild(div);
    scrollToBottom();
  }

  function appendAssistantBubble(id, content, ts) {
    // Si la bulle existe déjà (cas "start" suivi de "chunk"), on la met à jour
    const existing = document.querySelector(`[data-msg-id="${id}"]`);
    if (existing) {
      existing.innerHTML = renderMarkdown(content);
      return;
    }

    const div = document.createElement("div");
    div.className = "leo-ai-msg leo-ai-msg-assistant";
    div.innerHTML = `
      <div class="leo-ai-bubble" data-msg-id="${id}">${renderMarkdown(content)}</div>
      <div class="leo-ai-ts">${formatTs(ts)}</div>
    `;
    els.messages.appendChild(div);
    scrollToBottom();
  }

  function appendChunk(id, text) {
    let bubble = document.querySelector(`[data-msg-id="${id}"]`);
    if (!bubble) {
      // Fallback : crée la bulle si "start" n'a pas été reçu
      const div = document.createElement("div");
      div.className = "leo-ai-msg leo-ai-msg-assistant";
      div.innerHTML = `<div class="leo-ai-bubble" data-msg-id="${id}"></div><div class="leo-ai-ts">${formatTs()}</div>`;
      els.messages.appendChild(div);
      bubble = div.querySelector(`[data-msg-id="${id}"]`);
    }

    // Accumule le texte brut dans dataset (les marqueurs <<<ACTION>>> y sont conservés
    // pour l'extraction serveur), mais on les masque au rendu pour l'utilisateur.
    bubble.dataset.raw = (bubble.dataset.raw || "") + text;
    bubble.innerHTML = renderMarkdown(stripActionMarkers(bubble.dataset.raw));
    scrollToBottom();
  }

  function appendThinking() {
    removeThinking();
    const div = document.createElement("div");
    div.className = "leo-ai-msg leo-ai-msg-assistant leo-ai-thinking";
    div.id = "leo-ai-thinking-indicator";
    div.innerHTML = `
      <div class="leo-ai-bubble">
        <div class="leo-ai-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    `;
    els.messages.appendChild(div);
    scrollToBottom();
  }

  function removeThinking() {
    const el = $("leo-ai-thinking-indicator");
    if (el) el.remove();
  }

  function appendErrorMsg(msg) {
    const div = document.createElement("div");
    div.className = "leo-ai-msg leo-ai-msg-assistant";
    div.innerHTML = `
      <div class="leo-ai-bubble" style="border-color:rgba(255,77,109,.3);background:rgba(255,77,109,.06);">
        <span style="color:var(--red)">⚠</span> ${escapeHtml(msg)}
      </div>
    `;
    els.messages.appendChild(div);
    scrollToBottom();
  }

  // ── Cartes d'action ───────────────────────────────────────────────────────

  const ACTION_LABELS = {
    DRAFT_ORDER:   "Brouillon d'ordre",
    ADJUST_SL:     "Ajuster Stop Loss",
    ADJUST_TP:     "Ajuster Take Profit",
    SUGGEST_SIZE:  "Suggestion de taille",
    OPEN_MODAL:    "Ouvrir interface",
    INFO:          "Information",
  };

  function renderActionCards(msgId, actions, historical = false) {
    const msgEl = document.querySelector(`[data-msg-id="${msgId}"]`);
    const container = msgEl ? msgEl.closest(".leo-ai-msg") : els.messages;

    actions.forEach((action) => {
      const card = buildActionCard(action, historical);
      container.appendChild(card);
    });
  }

  function buildActionCard(action, historical) {
    const card = document.createElement("div");
    card.className = "leo-ai-action-card";
    card.id = `leo-ai-action-${action.id}`;
    if (historical && action.status !== "PROPOSED") {
      card.classList.add(action.status.toLowerCase());
    }

    const label = ACTION_LABELS[action.type] || action.type;
    const paramsHtml = buildParamsHtml(action.params || {});
    const isDone = historical && action.status !== "PROPOSED";

    card.innerHTML = `
      <div class="leo-ai-action-header">
        <span class="leo-ai-action-badge">${label}</span>
      </div>
      ${paramsHtml}
      ${action.rationale ? `<div class="leo-ai-action-rationale">"${escapeHtml(action.rationale)}"</div>` : ""}
      ${isDone
        ? `<div class="leo-ai-action-status ${action.status.toLowerCase()}">${action.status === "CONFIRMED" ? "✓ Confirmée" : "✕ Rejetée"}</div>`
        : `<div class="leo-ai-action-btns">
             <button class="leo-ai-action-confirm" data-action-id="${action.id}" onclick="LeoAssistant.confirmAction(${action.id})">
               ✓ Confirmer
             </button>
             <button class="leo-ai-action-reject" data-action-id="${action.id}" onclick="LeoAssistant.rejectAction(${action.id})">
               Ignorer
             </button>
           </div>`
      }
    `;
    return card;
  }

  function buildParamsHtml(params) {
    const entries = Object.entries(params).filter(([k]) => k !== "rationale");
    if (!entries.length) return "";
    const lines = entries.map(([k, v]) => `<span style="color:#6b7280">${escapeHtml(k)}</span>: <strong style="color:#e2e8f0">${escapeHtml(String(v))}</strong>`);
    return `<div class="leo-ai-action-params">${lines.join(" &nbsp;|&nbsp; ")}</div>`;
  }

  function updateActionCard(actionId, status, result) {
    const card = $(`leo-ai-action-${actionId}`);
    if (!card) return;

    const btns = card.querySelector(".leo-ai-action-btns");
    if (btns) btns.remove();

    const statusDiv = document.createElement("div");
    statusDiv.className = `leo-ai-action-status ${status.toLowerCase()}`;
    statusDiv.textContent = status === "CONFIRMED" ? "✓ Confirmée" : "✕ Rejetée";
    card.appendChild(statusDiv);
    card.classList.add(status.toLowerCase());
  }

  // ── Draft order modal ────────────────────────────────────────────────────

  function openDraftOrderModal(params) {
    // Tente d'ouvrir le formulaire d'ordre existant de LeoTrade
    // On dispatch un événement custom que les pages peuvent écouter
    window.dispatchEvent(new CustomEvent("leo:draft-order", { detail: params }));

    // Fallback : affiche les paramètres dans un message
    if (!params) return;
    const summary = Object.entries(params)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" | ");
    appendAssistantBubble("draft_" + Date.now(), `**Brouillon d'ordre prêt** :\n\n${summary}\n\nOuvrez le formulaire d'ordre pour finaliser l'exécution.`);
  }

  // ── Envoi de messages ─────────────────────────────────────────────────────

  function sendMessage(text, extraContext) {
    if (!text || !text.trim()) return;
    if (!state.isConnected) {
      connect();
      setTimeout(() => sendMessage(text, extraContext), 800);
      return;
    }
    if (state.isThinking) return;

    const ctx = { ...state.clientContext, ...(extraContext || {}) };

    appendUserBubble(text.trim());
    send({ type: "chat", message: text.trim(), context: ctx });

    // Reset suggestions après le premier message
    if (els.suggestions) els.suggestions.style.display = "none";
  }

  // ── Actions confirm/reject ────────────────────────────────────────────────

  function confirmAction(actionId) {
    send({ type: "action_confirm", action_id: actionId });
    decrementBadge();
  }

  function rejectAction(actionId) {
    send({ type: "action_reject", action_id: actionId });
    decrementBadge();
  }

  // ── Explication d'une opportunité ─────────────────────────────────────────

  function explainOpportunity(id, direction, symbol, timeframe, score, confidence) {
    const msg = `Explique-moi en détail cette opportunité : ${direction} sur ${symbol} (${timeframe}).
Score IA : ${score ?? "?"} | Confiance : ${confidence ?? "?"}.
Analyse les indicateurs, le R/R, les risques, et donne-moi un conseil.`;

    const ctx = { opportunity_id: id, page: "opportunities" };
    open();
    setTimeout(() => sendMessage(msg, ctx), 300);
  }

  // ── Contexte page ─────────────────────────────────────────────────────────

  function updatePageContext(page, extra) {
    state.clientContext = { page, ...(extra || {}) };
    if (els.pageLabel) els.pageLabel.textContent = PAGE_LABELS[page] || page;
    send({ type: "context_update", context: state.clientContext });
  }

  const PAGE_LABELS = {
    dashboard: "Dashboard",
    opportunities: "Opportunités IA",
    portfolio: "Portefeuille",
    positions: "Positions",
    history: "Historique",
    risk: "Risque",
    orders: "Ordres",
    watchlist: "Watchlist",
  };

  // ── UI helpers ────────────────────────────────────────────────────────────

  function open() {
    if (!els.panel) return;
    state.isOpen = true;
    els.panel.classList.add("leo-ai-open");
    els.panel.setAttribute("aria-hidden", "false");
    els.toggle.classList.add("leo-ai-open");
    if (window.innerWidth < 768 && els.overlay) {
      els.overlay.classList.add("leo-ai-open");
    }
    if (!state.isConnected) connect();
    els.input && els.input.focus();
  }

  function close() {
    if (!els.panel) return;
    state.isOpen = false;
    els.panel.classList.remove("leo-ai-open");
    els.panel.setAttribute("aria-hidden", "true");
    els.toggle.classList.remove("leo-ai-open");
    if (els.overlay) els.overlay.classList.remove("leo-ai-open");
  }

  function toggle() {
    state.isOpen ? close() : open();
  }

  function clearSession() {
    if (!els.messages) return;
    els.messages.innerHTML = "";
    appendWelcome();
    if (els.suggestions) els.suggestions.style.display = "";
    // Permet de recharger l'historique (vide) à la prochaine reconnexion
    state.historyLoaded = false;
    // Ferme la session côté serveur en en créant une nouvelle
    send({ type: "context_update", context: { ...state.clientContext, _new_session: true } });
  }

  function setStatus(status, text) {
    if (!els.statusDot || !els.statusText) return;
    els.statusDot.className = "leo-ai-status-dot" + (status === "offline" ? " offline" : "");
    els.statusText.textContent = text;
    // Active le bouton d'envoi dès que connecté
    setSendDisabled(status !== "connected");
  }

  function setSendDisabled(disabled) {
    if (!els.sendBtn) return;
    els.sendBtn.disabled = disabled || !els.input || !els.input.value.trim();
  }

  function scrollToBottom() {
    if (!els.messages) return;
    requestAnimationFrame(() => {
      els.messages.scrollTop = els.messages.scrollHeight;
    });
  }

  function updateBadge(count) {
    state.pendingActionsCount += count;
    if (!els.badge) return;
    if (state.pendingActionsCount > 0) {
      els.badge.textContent = state.pendingActionsCount;
      els.badge.classList.add("visible");
    } else {
      els.badge.classList.remove("visible");
    }
  }

  function decrementBadge() {
    state.pendingActionsCount = Math.max(0, state.pendingActionsCount - 1);
    updateBadge(0);
  }

  function showKillSwitchBanner(show) {
    if (!els.ksBanner) return;
    els.ksBanner.classList.toggle("visible", show);
  }

  // ── Nettoyage des marqueurs d'action ─────────────────────────────────────

  const ACTION_BLOCK_RE = /<<<ACTION>>>[\s\S]*?<<<END_ACTION>>>/g;

  /**
   * Supprime les blocs <<<ACTION>>>...<<<END_ACTION>>> du texte.
   * Utilisé côté client pour ne jamais afficher ces marqueurs dans les bulles.
   */
  function stripActionMarkers(text) {
    return text.replace(ACTION_BLOCK_RE, "").trim();
  }

  // ── Markdown léger ────────────────────────────────────────────────────────

  function renderMarkdown(text) {
    if (!text) return "";
    let s = escapeHtml(text);

    // Sections titre : **Titre** ou __Titre__ en début de ligne
    s = s.replace(/^\*\*([^*]+)\*\*\s*$/gm, '<div class="leo-ai-section-title">$1</div>');
    // Bold
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Code inline
    s = s.replace(/`(.+?)`/g, '<code>$1</code>');
    // Listes (• ou -)
    s = s.replace(/^[•\-]\s+(.+)$/gm, '<li>$1</li>');
    s = s.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    // Sauts de ligne
    s = s.replace(/\n\n/g, '</p><p>');
    s = s.replace(/\n/g, '<br>');
    if (!s.startsWith('<p>') && !s.startsWith('<div>') && !s.startsWith('<ul>')) {
      s = '<p>' + s + '</p>';
    }
    return s;
  }

  function escapeHtml(str) {
    if (typeof str !== "string") return String(str ?? "");
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatTs(iso) {
    if (!iso) return new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  }

  // ── Initialisation ────────────────────────────────────────────────────────

  function init() {
    initEls();
    if (!els.panel) return;

    // Page context initial
    const page = document.body.dataset.leoPage || "dashboard";
    updatePageContext(page);

    // Connexion WS immédiate (panel fermé mais WS prêt)
    connect();

    // Handlers UI
    els.toggle && els.toggle.addEventListener("click", toggle);
    els.closeBtn && els.closeBtn.addEventListener("click", close);
    els.clearBtn && els.clearBtn.addEventListener("click", clearSession);
    els.overlay && els.overlay.addEventListener("click", close);

    // Envoi message
    els.sendBtn && els.sendBtn.addEventListener("click", () => {
      const text = els.input.value.trim();
      if (text) {
        sendMessage(text);
        els.input.value = "";
        els.input.style.height = "auto";
        setSendDisabled(true);
      }
    });

    els.input && els.input.addEventListener("input", () => {
      // Auto-resize textarea
      els.input.style.height = "auto";
      els.input.style.height = Math.min(els.input.scrollHeight, 120) + "px";
      setSendDisabled(!els.input.value.trim() || !state.isConnected || state.isThinking);
    });

    els.input && els.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        els.sendBtn && !els.sendBtn.disabled && els.sendBtn.click();
      }
    });

    // Boutons de suggestions rapides
    document.querySelectorAll(".leo-ai-suggestion-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const msg = btn.dataset.msg;
        if (msg) sendMessage(msg);
      });
    });

    // Boutons "Expliquer" sur les cartes d'opportunités
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-leo-explain-opp]");
      if (!btn) return;
      const { id, direction, symbol, timeframe, score, confidence } = btn.dataset;
      explainOpportunity(id, direction, symbol, timeframe, score, confidence);
    });

    // Raccourci clavier global : Ctrl+Shift+A
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "A") {
        e.preventDefault();
        toggle();
      }
    });

    // Écoute l'événement de changement de page (SPA-like)
    window.addEventListener("leo:page-change", (e) => {
      updatePageContext(e.detail.page, e.detail.extra);
    });
  }

  // ── API publique ──────────────────────────────────────────────────────────

  window.LeoAssistant = {
    open,
    close,
    toggle,
    sendMessage,
    confirmAction,
    rejectAction,
    explainOpportunity,
    updatePageContext,
    isOpen: () => state.isOpen,
  };

  // Init au DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})(window);
