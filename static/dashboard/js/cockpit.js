/* =============================================================================
 * cockpit.js — Cockpit Premium (refactor 2026-04-28)
 *
 * Changements vs version précédente :
 *   - Utilise LeoWS (backoff exponentiel + état partagé)
 *   - prependActivity() utilise textContent / append (plus d'innerHTML — XSS fix)
 *   - Plus de connectSocket inline — un seul point d'entrée par flux
 *   - Émet des animations flash quand les valeurs financières changent
 *     (helper LeoAnim si chargé, sinon update silencieux)
 *
 * Dépendances :
 *   - /static/js/leo_websocket.js  (LeoWS)
 *   - /static/js/leo_animations.js (LeoAnim, optionnel)
 * ============================================================================= */

(function () {
  const cfg = window.LEOTRADE_COCKPIT;
  if (!cfg) return;
  if (!window.LeoWS) {
    console.error("[cockpit] LeoWS manquant. Charge /static/js/leo_websocket.js avant cockpit.js");
    return;
  }

  // ---------- helpers ----------

  function setText(selector, value) {
    if (value === undefined || value === null) return;
    const el = document.querySelector(selector);
    if (!el) return;

    const previous = el.dataset.previousValue;
    el.textContent = String(value);

    // Flash visuel (vert si hausse, rouge si baisse) si LeoAnim dispo
    if (window.LeoAnim && previous !== undefined) {
      window.LeoAnim.flashValue(el, value, previous);
    }
    el.dataset.previousValue = String(value);
  }

  /**
   * Insère une ligne dans le feed d'activité.
   * SANS innerHTML — sécurisé contre XSS via les payloads broker.
   */
  function prependActivity(title, subtitle) {
    const feed = document.querySelector("#activity-feed-list");
    if (!feed) return;

    const item = document.createElement("div");
    item.className = "rounded-xl bg-slate-950/80 p-4 leo-fade-in";

    const head = document.createElement("div");
    head.className = "flex items-center justify-between gap-3";

    const titleEl = document.createElement("div");
    titleEl.className = "font-semibold text-white";
    titleEl.textContent = String(title || "Événement");

    const timeEl = document.createElement("div");
    timeEl.className = "text-xs text-slate-500";
    timeEl.textContent = "maintenant";

    head.appendChild(titleEl);
    head.appendChild(timeEl);

    const subtitleEl = document.createElement("div");
    subtitleEl.className = "mt-1 text-sm text-slate-400";
    subtitleEl.textContent = String(subtitle || "");

    item.appendChild(head);
    item.appendChild(subtitleEl);

    feed.prepend(item);

    // Cap à 12 entrées pour éviter une croissance infinie du DOM
    while (feed.children.length > 12) {
      feed.removeChild(feed.lastElementChild);
    }
  }

  /**
   * Rafraîchissement HTTP à intervalle long.
   * Le push WebSocket reste la source primaire ; ce poll est un filet de
   * sécurité au cas où une mise à jour aurait été ratée.
   */
  function refreshCockpitData() {
    const url = `${cfg.cockpitDataUrl}?portfolio=${encodeURIComponent(cfg.portfolioId)}`;
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => r.json())
      .then((data) => {
        if (!data || !data.hero_stats) return;
        setText("[data-dashboard-balance]", data.hero_stats.balance);
        setText("[data-dashboard-equity]", data.hero_stats.equity);
        setText("[data-dashboard-available-cash]", data.hero_stats.available_cash);
        setText("[data-dashboard-unrealized]", data.hero_stats.unrealized_pnl);
        setText("[data-dashboard-drawdown]", `${data.hero_stats.drawdown}%`);
      })
      .catch((err) => console.warn("[cockpit] refresh failed", err));
  }

  // ---------- Connexions WebSocket ----------

  LeoWS.connect(cfg.wsPortfolioUrl, {
    name: "portfolio",
    expectedEvent: "portfolio.update",
    onMessage: function (_data, payload) {
      setText("[data-dashboard-balance]", payload.balance);
      setText("[data-dashboard-equity]", payload.equity);
      setText("[data-dashboard-available-cash]", payload.available_cash);
      setText("[data-dashboard-unrealized]", payload.unrealized_pnl);
      if (payload.drawdown !== undefined) {
        setText("[data-dashboard-drawdown]", `${payload.drawdown}%`);
      }
      prependActivity("Portfolio update", payload.kind || "Mise à jour portefeuille");
    },
  });

  LeoWS.connect(cfg.wsOrdersUrl, {
    name: "orders",
    expectedEvent: "order.update",
    onMessage: function (_data, payload) {
      prependActivity(
        `Ordre ${payload.symbol || ""}`,
        `${payload.kind || "update"} · ${payload.status || ""}`
      );
      refreshCockpitData();
    },
  });

  LeoWS.connect(cfg.wsNotificationsUrl, {
    name: "notifications",
    expectedEvent: "notification",
    onMessage: function (_data, payload) {
      if (payload.message) prependActivity("Notification", payload.message);
    },
  });

  LeoWS.connect(cfg.wsDashboardUrl, {
    name: "dashboard",
    expectedEvent: "dashboard.update",
    onMessage: function (_data, payload) {
      if (payload.kind === "portfolio_metrics") {
        setText("[data-dashboard-balance]", payload.balance);
        setText("[data-dashboard-equity]", payload.equity);
        setText("[data-dashboard-unrealized]", payload.unrealized_pnl);
        if (payload.drawdown !== undefined) {
          setText("[data-dashboard-drawdown]", `${payload.drawdown}%`);
        }
      }
      prependActivity("Dashboard live", payload.kind || "update");
    },
  });

  LeoWS.connect(cfg.wsAiRadarUrl, {
    name: "ai_radar",
    expectedEvent: "ai.update",
    onMessage: function (_data, payload) {
      prependActivity(
        `IA ${payload.symbol || ""}`,
        `${payload.kind || "recommendation"} · ${payload.recommendation_type || ""}`
      );
      refreshCockpitData();
    },
  });

  // Filet de sécurité : poll toutes les 60s (était 30s mais maintenant le WS
  // a une reconnexion fiable et propage l'état "offline" → l'utilisateur sait)
  setInterval(refreshCockpitData, 60_000);
})();
