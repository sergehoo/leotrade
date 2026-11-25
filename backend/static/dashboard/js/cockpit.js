/* =============================================================================
 * cockpit.js — Cockpit Premium Lyneci
 *
 * v2 — Graphiques temps réel, animations, WebSocket multi-flux.
 *
 * Dépendances (dans l'ordre de chargement) :
 *   1. Chart.js 4.x
 *   2. /static/js/leo_websocket.js   (LeoWS)
 *   3. /static/js/leo_animations.js  (LeoAnim)
 *   4. /static/js/leo_charts.js      (LeoCharts)
 *
 * Sécurité : pas d'innerHTML, textContent uniquement.
 * ============================================================================= */

(function () {
  "use strict";

  const cfg = window.LYNECI_COCKPIT;
  if (!cfg) return;
  if (!window.LeoWS) {
    console.error("[cockpit] LeoWS manquant.");
    return;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  function setText(selector, value) {
    if (value === undefined || value === null) return;
    const el = document.querySelector(selector);
    if (!el) return;
    const previous = el.dataset.previousValue;
    el.textContent = String(value);
    if (window.LeoAnim && previous !== undefined) {
      window.LeoAnim.flashValue(el, value, previous);
    }
    el.dataset.previousValue = String(value);
  }

  function setClass(selector, add, remove) {
    const el = document.querySelector(selector);
    if (!el) return;
    if (remove) el.classList.remove(...(Array.isArray(remove) ? remove : [remove]));
    if (add)    el.classList.add(...(Array.isArray(add) ? add : [add]));
  }

  function prependActivity(title, subtitle, kind) {
    const feed = document.querySelector("#activity-feed-list");
    if (!feed) return;

    const kindColor = {
      order:    "text-blue-400",
      ai:       "text-purple-400",
      risk:     "text-amber-400",
      error:    "text-red-400",
      default:  "text-slate-300",
    };
    const colorClass = kindColor[kind] || kindColor.default;

    const item = document.createElement("div");
    item.className = "rounded-xl bg-slate-950/80 p-3 leo-fade-in border border-slate-800/60";

    const head = document.createElement("div");
    head.className = "flex items-center justify-between gap-2";

    const titleEl = document.createElement("div");
    titleEl.className = `font-semibold text-sm ${colorClass}`;
    titleEl.textContent = String(title || "Événement");

    const timeEl = document.createElement("div");
    timeEl.className = "text-xs text-slate-600 shrink-0";
    timeEl.textContent = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    head.appendChild(titleEl);
    head.appendChild(timeEl);

    const subtitleEl = document.createElement("div");
    subtitleEl.className = "mt-0.5 text-xs text-slate-400 leading-relaxed";
    subtitleEl.textContent = String(subtitle || "");

    item.appendChild(head);
    item.appendChild(subtitleEl);

    feed.prepend(item);

    while (feed.children.length > 20) {
      feed.removeChild(feed.lastElementChild);
    }

    if (window.LeoAnim) LeoAnim.fadeIn(item);
  }

  // ── Graphique P&L ────────────────────────────────────────────────────────

  let pnlChart = null;

  function initPnlChart() {
    if (!window.LeoCharts) return;
    const snapshots = cfg.pnlSnapshots || [];
    const labels = snapshots.map((s) => {
      const d = new Date(s.snapshot_time || s.time || "");
      return isNaN(d) ? "" : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    });
    const data = snapshots.map((s) => parseFloat(s.total_value || s.equity || 0));

    pnlChart = LeoCharts.pnlLine("pnl-chart", {
      labels,
      data,
      currency: "$",
      maxPoints: 60,
    });

    updatePnlLabel(data);
  }

  function updatePnlLabel(data) {
    if (!data || data.length < 2) return;
    const first = data[0], last = data[data.length - 1];
    const diff = last - first;
    const pct  = first ? ((diff / first) * 100).toFixed(2) : "0.00";
    const sign = diff >= 0 ? "+" : "";
    const el   = document.getElementById("pnl-chart-label");
    const pEl  = document.getElementById("pnl-chart-pct");
    if (el)  el.textContent = `$${Number(last).toLocaleString("fr-FR", { minimumFractionDigits: 2 })}`;
    if (pEl) {
      pEl.textContent = `${sign}${pct}%`;
      pEl.className = `text-xs font-semibold ${diff >= 0 ? "text-emerald-400" : "text-red-400"}`;
    }
  }

  function addPnlPoint(value) {
    if (!pnlChart) return;
    const label = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    pnlChart.leoAddPoint(label, parseFloat(value));
    const data = pnlChart.data.datasets[0].data;
    updatePnlLabel(data);
  }

  // ── Donut répartition ────────────────────────────────────────────────────

  let donutChart = null;

  function initDonutChart() {
    if (!window.LeoCharts) return;
    const alloc = cfg.allocationData || {};
    donutChart = LeoCharts.portfolioDonut("allocation-donut", {
      labels: alloc.labels || [],
      values: alloc.values || [],
    });
  }

  // ── Jauge risque ─────────────────────────────────────────────────────────

  let riskGauge = null;

  function initRiskGauge() {
    if (!window.LeoCharts) return;
    const val = parseFloat(cfg.riskDrawdown || 0);
    riskGauge = LeoCharts.riskGauge("risk-gauge", val);
    const lbl = document.getElementById("risk-gauge-label");
    if (lbl) lbl.textContent = `${(val * 100).toFixed(1)}% drawdown utilisé`;
  }

  function updateRiskGauge(value) {
    if (!riskGauge) return;
    riskGauge.leoSetValue(value);
    const lbl = document.getElementById("risk-gauge-label");
    if (lbl) lbl.textContent = `${(value * 100).toFixed(1)}% drawdown utilisé`;
  }

  // ── Refresh HTTP (filet de sécurité) ─────────────────────────────────────

  function refreshCockpitData() {
    const url = `${cfg.cockpitDataUrl}?portfolio=${encodeURIComponent(cfg.portfolioId)}`;
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => r.json())
      .then((data) => {
        if (!data) return;

        const h = data.hero_stats || {};
        setText("[data-dashboard-balance]",        h.balance);
        setText("[data-dashboard-equity]",          h.equity);
        setText("[data-dashboard-available-cash]",  h.available_cash);
        setText("[data-dashboard-unrealized]",      h.unrealized_pnl);
        if (h.drawdown !== undefined) setText("[data-dashboard-drawdown]", `${h.drawdown}%`);

        // Mise à jour graphique P&L
        if (data.pnl_snapshots && data.pnl_snapshots.length && pnlChart) {
          const labels = data.pnl_snapshots.map((s) => {
            const d = new Date(s.snapshot_time || "");
            return isNaN(d) ? "" : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
          });
          const values = data.pnl_snapshots.map((s) => parseFloat(s.total_value || 0));
          pnlChart.leoSetData(labels, values);
          updatePnlLabel(values);
        }

        // Mise à jour jauge risque
        if (data.risk_drawdown !== undefined) updateRiskGauge(parseFloat(data.risk_drawdown));

        // Mise à jour donut
        if (data.allocation && donutChart) {
          donutChart.leoUpdate(data.allocation.labels || [], data.allocation.values || []);
        }
      })
      .catch((err) => console.warn("[cockpit] refresh failed", err));
  }

  // ── Connexions WebSocket ──────────────────────────────────────────────────

  LeoWS.connect(cfg.wsPortfolioUrl, {
    name: "portfolio",
    expectedEvent: "portfolio.update",
    onMessage: function (_data, payload) {
      setText("[data-dashboard-balance]",       payload.balance);
      setText("[data-dashboard-equity]",         payload.equity);
      setText("[data-dashboard-available-cash]", payload.available_cash);
      setText("[data-dashboard-unrealized]",     payload.unrealized_pnl);
      if (payload.drawdown !== undefined) {
        setText("[data-dashboard-drawdown]", `${payload.drawdown}%`);
        updateRiskGauge(parseFloat(payload.drawdown) / 100);
      }
      // Ajouter un point au graphique P&L
      if (payload.equity !== undefined) addPnlPoint(payload.equity);

      prependActivity("Portfolio mis à jour", payload.kind || "update", "default");
    },
  });

  LeoWS.connect(cfg.wsOrdersUrl, {
    name: "orders",
    expectedEvent: "order.update",
    onMessage: function (_data, payload) {
      const isBuy  = (payload.side || "").toUpperCase() === "BUY";
      const status = (payload.status || "").toLowerCase();
      const icon   = status === "filled" ? (isBuy ? "↑" : "↓") : "◎";
      prependActivity(
        `${icon} ${payload.symbol || "Ordre"}`,
        `${payload.kind || "update"} · ${payload.status || ""}`,
        "order"
      );
      if (window.LeoAnim) {
        LeoAnim.toast(
          `${payload.symbol || "Ordre"} ${payload.status || "update"}`,
          status === "filled" ? "success" : status === "rejected" ? "error" : "info"
        );
      }
      // Refresh pour mettre à jour la table des positions
      setTimeout(refreshCockpitData, 500);
    },
  });

  LeoWS.connect(cfg.wsNotificationsUrl, {
    name: "notifications",
    expectedEvent: "notification",
    onMessage: function (_data, payload) {
      if (payload.message) {
        prependActivity("Notification", payload.message, "default");
        if (window.LeoAnim) LeoAnim.toast(payload.message, payload.level || "info");
      }
    },
  });

  LeoWS.connect(cfg.wsDashboardUrl, {
    name: "dashboard",
    expectedEvent: "dashboard.update",
    onMessage: function (_data, payload) {
      if (payload.kind === "portfolio_metrics") {
        setText("[data-dashboard-balance]",    payload.balance);
        setText("[data-dashboard-equity]",      payload.equity);
        setText("[data-dashboard-unrealized]",  payload.unrealized_pnl);
        if (payload.equity !== undefined) addPnlPoint(payload.equity);
        if (payload.drawdown !== undefined) {
          setText("[data-dashboard-drawdown]", `${payload.drawdown}%`);
          updateRiskGauge(parseFloat(payload.drawdown) / 100);
        }
      } else if (payload.kind === "risk_update") {
        if (payload.drawdown_pct !== undefined) updateRiskGauge(parseFloat(payload.drawdown_pct));
      }
    },
  });

  LeoWS.connect(cfg.wsAiRadarUrl, {
    name: "ai_radar",
    expectedEvent: "ai.update",
    onMessage: function (_data, payload) {
      const action = (payload.recommendation_type || payload.kind || "signal").toUpperCase();
      prependActivity(
        `IA · ${payload.symbol || "Market"} ${action}`,
        `Confiance ${payload.confidence_score ? Math.round(payload.confidence_score * 100) + "%" : "—"}`,
        "ai"
      );
      if (window.LeoAnim) {
        LeoAnim.toast(`Signal IA : ${payload.symbol || ""} ${action}`, "info");
      }
    },
  });

  // ── Init ─────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    initPnlChart();
    initDonutChart();
    initRiskGauge();
  });

  // Filet de sécurité : refresh complet toutes les 90s
  setInterval(refreshCockpitData, 90_000);

})();
