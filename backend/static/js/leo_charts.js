/* =============================================================================
 * leo_charts.js — Graphiques financiers temps réel pour Lyneci
 * =============================================================================
 *
 * Fournit :
 *   LeoCharts.pnlLine(canvasId, options)       → courbe P&L animée
 *   LeoCharts.portfolioDonut(canvasId, data)   → répartition de portefeuille
 *   LeoCharts.riskGauge(canvasId, value)       → jauge de risque
 *   LeoCharts.candlestick(canvasId, options)   → chandeliers temps réel
 *   LeoCharts.miniSparkline(canvasId, data)    → mini courbe sans axes
 *
 * Dépend de Chart.js >= 4.x (CDN ou local).
 * Aucun innerHTML, aucune dépendance externe autre que Chart.js.
 * ============================================================================= */

(function (global) {
  "use strict";

  if (!global.Chart) {
    console.warn("[LeoCharts] Chart.js non chargé. Ajoute la balise <script> Chart.js avant leo_charts.js.");
    // On expose quand même l'API pour éviter les erreurs JS dans les templates
    global.LeoCharts = { pnlLine: () => null, portfolioDonut: () => null, riskGauge: () => null, candlestick: () => null, miniSparkline: () => null };
    return;
  }

  Chart.defaults.color = "#8B9BB4";
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.font.size = 12;

  // Palette Lyneci
  const C = {
    profit:  "#00D4AA",
    loss:    "#FF4C6A",
    primary: "#4F8EF7",
    ai:      "#9D6FE8",
    warning: "#FFB84D",
    bg:      "#161A24",
    surface: "#1E2333",
    border:  "#2A3045",
    muted:   "#4A5568",
    text:    "#EBF0F5",
  };

  function gradient(ctx, colorStart, colorEnd) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
    g.addColorStop(0, colorStart);
    g.addColorStop(1, colorEnd);
    return g;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // P&L Line — courbe animée avec gradient sous la courbe
  // ═══════════════════════════════════════════════════════════════════════════
  function pnlLine(canvasId, options) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const opts = Object.assign({
      labels: [],
      data: [],
      currency: "$",
      maxPoints: 60,          // nombre max de points affichés en glissant
      animationDuration: 400, // ms par update temps réel
    }, options || {});

    const isPositive = () =>
      opts.data.length >= 2
        ? opts.data[opts.data.length - 1] >= opts.data[0]
        : true;

    const lineColor = () => isPositive() ? C.profit : C.loss;

    const chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [...opts.labels],
        datasets: [{
          label: "P&L",
          data: [...opts.data],
          borderColor: lineColor(),
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: lineColor(),
          tension: 0.4,
          fill: true,
          backgroundColor: (context) => {
            const chart = context.chart;
            const { ctx: c, chartArea } = chart;
            if (!chartArea) return "transparent";
            const color = lineColor();
            const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            g.addColorStop(0, color + "33");
            g.addColorStop(1, color + "00");
            return g;
          },
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: opts.animationDuration, easing: "easeInOutQuart" },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: C.surface,
            borderColor: C.border,
            borderWidth: 1,
            padding: 10,
            callbacks: {
              label: (ctx) => ` ${opts.currency}${Number(ctx.raw).toLocaleString("fr-FR", { minimumFractionDigits: 2 })}`,
            },
          },
        },
        scales: {
          x: {
            display: true,
            grid: { color: C.border + "44", drawBorder: false },
            ticks: { maxTicksLimit: 6, color: C.muted, font: { size: 10 } },
          },
          y: {
            display: true,
            position: "right",
            grid: { color: C.border + "44", drawBorder: false },
            ticks: {
              color: C.muted,
              font: { size: 10 },
              callback: (v) => `${opts.currency}${Number(v).toLocaleString("fr-FR")}`,
            },
          },
        },
      },
    });

    // API temps réel
    chart.leoAddPoint = function (label, value) {
      const ds = chart.data.datasets[0];
      chart.data.labels.push(label);
      ds.data.push(value);

      if (chart.data.labels.length > opts.maxPoints) {
        chart.data.labels.shift();
        ds.data.shift();
      }

      // Mise à jour couleur selon tendance courante
      const col = lineColor();
      ds.borderColor = col;
      ds.pointHoverBackgroundColor = col;

      chart.update("active");
    };

    chart.leoSetData = function (labels, data) {
      chart.data.labels = [...labels];
      chart.data.datasets[0].data = [...data];
      const col = lineColor();
      chart.data.datasets[0].borderColor = col;
      chart.update();
    };

    return chart;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Portfolio Donut — répartition des actifs
  // ═══════════════════════════════════════════════════════════════════════════
  function portfolioDonut(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const colors = [C.primary, C.profit, C.ai, C.warning, C.loss,
                    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#6366F1"];

    const chart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: data.labels || [],
        datasets: [{
          data: data.values || [],
          backgroundColor: colors.slice(0, (data.values || []).length),
          borderColor: C.bg,
          borderWidth: 3,
          hoverOffset: 8,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "72%",
        animation: { duration: 600, easing: "easeOutQuart" },
        plugins: {
          legend: {
            position: "bottom",
            labels: { padding: 16, usePointStyle: true, pointStyleWidth: 10 },
          },
          tooltip: {
            backgroundColor: C.surface,
            borderColor: C.border,
            borderWidth: 1,
            callbacks: {
              label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(1)}%`,
            },
          },
        },
      },
    });

    chart.leoUpdate = function (labels, values) {
      chart.data.labels = [...labels];
      chart.data.datasets[0].data = [...values];
      chart.data.datasets[0].backgroundColor = colors.slice(0, values.length);
      chart.update();
    };

    return chart;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Risk Gauge — demi-cercle animé
  // ═══════════════════════════════════════════════════════════════════════════
  function riskGauge(canvasId, value) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    // value ∈ [0, 1]
    const pct = Math.max(0, Math.min(1, value || 0));

    const gaugeColor = pct < 0.5 ? C.profit : pct < 0.75 ? C.warning : C.loss;
    const remaining = 1 - pct;

    const chart = new Chart(ctx, {
      type: "doughnut",
      data: {
        datasets: [{
          data: [pct, remaining],
          backgroundColor: [gaugeColor, C.border],
          borderWidth: 0,
          circumference: 180,
          rotation: 270,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "80%",
        animation: { duration: 700, easing: "easeOutQuart" },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });

    chart.leoSetValue = function (newValue) {
      const p = Math.max(0, Math.min(1, newValue));
      const color = p < 0.5 ? C.profit : p < 0.75 ? C.warning : C.loss;
      chart.data.datasets[0].data = [p, 1 - p];
      chart.data.datasets[0].backgroundColor[0] = color;
      chart.update();
    };

    return chart;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Mini Sparkline — courbe sans axes, pour les tableaux de positions
  // ═══════════════════════════════════════════════════════════════════════════
  function miniSparkline(canvasId, data, positive) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const color = positive !== false ? C.profit : C.loss;

    const chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: data.map((_, i) => i),
        datasets: [{
          data: data,
          borderColor: color,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.4,
          fill: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { display: false },
        },
      },
    });

    chart.leoAddPoint = function (value) {
      chart.data.datasets[0].data.push(value);
      chart.data.labels.push(chart.data.labels.length);
      if (chart.data.datasets[0].data.length > 30) {
        chart.data.datasets[0].data.shift();
        chart.data.labels.shift();
      }
      chart.update("active");
    };

    return chart;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Candlestick simplifié (OHLC bars) — temps réel via WS
  // Nécessite chartjs-chart-financial ou fallback sur bar-chart.
  // ═══════════════════════════════════════════════════════════════════════════
  function candlestick(canvasId, options) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Si le plugin financier est disponible, on l'utilise
    if (global.CandlestickController) {
      return _realCandlestick(canvas, options);
    }
    // Fallback : courbe OHLC simplifiée (close price)
    return pnlLine(canvasId, {
      labels: (options.candles || []).map(c => c.time || ""),
      data:   (options.candles || []).map(c => c.close || 0),
      currency: options.currency || "$",
    });
  }

  function _realCandlestick(canvas, options) {
    const ctx = canvas.getContext("2d");
    const candles = options.candles || [];
    const chart = new Chart(ctx, {
      type: "candlestick",
      data: {
        datasets: [{
          label: options.symbol || "OHLC",
          data: candles.map(c => ({ x: c.time, o: c.open, h: c.high, l: c.low, c: c.close })),
          color: { up: C.profit, down: C.loss, unchanged: C.muted },
          borderColor: { up: C.profit, down: C.loss, unchanged: C.muted },
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: C.border + "44" }, ticks: { color: C.muted } },
          y: { grid: { color: C.border + "44" }, ticks: { color: C.muted }, position: "right" },
        },
      },
    });

    chart.leoAddCandle = function (candle) {
      const ds = chart.data.datasets[0];
      ds.data.push({ x: candle.time, o: candle.open, h: candle.high, l: candle.low, c: candle.close });
      if (ds.data.length > 100) ds.data.shift();
      chart.update("active");
    };

    chart.leoUpdateLastCandle = function (candle) {
      const ds = chart.data.datasets[0];
      if (ds.data.length > 0) {
        ds.data[ds.data.length - 1] = { x: candle.time, o: candle.open, h: candle.high, l: candle.low, c: candle.close };
        chart.update("active");
      }
    };

    return chart;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // API publique
  // ═══════════════════════════════════════════════════════════════════════════
  global.LeoCharts = { pnlLine, portfolioDonut, riskGauge, candlestick, miniSparkline };

})(window);
