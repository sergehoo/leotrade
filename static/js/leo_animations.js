/* =============================================================================
 * leo_animations.js — Helpers d'animations financières
 * =============================================================================
 *
 * Dépend de : /static/css/leo_animations.css
 *
 * API publique :
 *   LeoAnim.flashValue(el, newValue, oldValue);
 *      → Détecte la direction et applique .leo-flash-up ou .leo-flash-down
 *        sur l'élément pendant ~600ms.
 *
 *   LeoAnim.fadeIn(el);   → applique .leo-fade-in (transitoire)
 *   LeoAnim.fadeOut(el, onComplete); → fade out + callback (ex: avant remove)
 *
 *   LeoAnim.parseNumber("1 234,56 €")  → 1234.56
 *
 *   LeoAnim.tickRow(rowEl, deltaSign);  → highlight ligne en hausse/baisse
 *
 *   LeoAnim.toast(message, kind);   → toast en haut à droite
 *      kind ∈ "success" | "error" | "info" (défaut "info")
 *
 * Aucune dépendance externe. Aucun innerHTML.
 * ============================================================================= */

(function (global) {
  "use strict";

  function parseNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === "number") return value;
    let s = String(value).trim();
    // Retire les unités, espaces fines, devises courantes
    s = s.replace(/[\s  ]/g, "");
    s = s.replace(/[€$£¥%]/g, "");
    // Si la chaîne contient une virgule décimale (format FR), normalise
    if (s.indexOf(",") > -1 && s.lastIndexOf(",") > s.lastIndexOf(".")) {
      s = s.replace(/\./g, "").replace(",", ".");
    }
    const n = parseFloat(s);
    return isFinite(n) ? n : NaN;
  }

  function flashValue(el, newValue, oldValue) {
    if (!el) return;
    const newN = parseNumber(newValue);
    const oldN = parseNumber(oldValue);

    if (!isFinite(newN) || !isFinite(oldN) || newN === oldN) return;

    const cls = newN > oldN ? "leo-flash-up" : "leo-flash-down";
    // Reset si déjà en cours pour relancer l'anim
    el.classList.remove("leo-flash-up", "leo-flash-down");
    // Force le reflow pour rejouer l'animation
    void el.offsetWidth;
    el.classList.add(cls);

    setTimeout(() => {
      el.classList.remove(cls);
    }, 600);
  }

  function fadeIn(el) {
    if (!el) return;
    el.classList.remove("leo-fade-out");
    el.classList.add("leo-fade-in");
    setTimeout(() => el.classList.remove("leo-fade-in"), 350);
  }

  function fadeOut(el, onComplete) {
    if (!el) return;
    el.classList.remove("leo-fade-in");
    el.classList.add("leo-fade-out");
    setTimeout(() => {
      el.classList.remove("leo-fade-out");
      if (typeof onComplete === "function") onComplete();
    }, 320);
  }

  function tickRow(rowEl, deltaSign) {
    if (!rowEl) return;
    const cls = deltaSign > 0 ? "leo-flash-up" : "leo-flash-down";
    rowEl.classList.remove("leo-flash-up", "leo-flash-down");
    void rowEl.offsetWidth;
    rowEl.classList.add(cls);
    setTimeout(() => rowEl.classList.remove(cls), 600);
  }

  // ---------- Toasts ----------

  function ensureToastContainer() {
    let c = document.getElementById("leo-toast-container");
    if (c) return c;
    c = document.createElement("div");
    c.id = "leo-toast-container";
    c.style.cssText = [
      "position: fixed",
      "top: 16px",
      "right: 16px",
      "z-index: 9999",
      "display: flex",
      "flex-direction: column",
      "gap: 8px",
      "max-width: 360px",
      "pointer-events: none",
    ].join(";");
    c.setAttribute("role", "region");
    c.setAttribute("aria-label", "Notifications");
    c.setAttribute("aria-live", "polite");
    document.body.appendChild(c);
    return c;
  }

  function toast(message, kind) {
    const container = ensureToastContainer();
    const t = document.createElement("div");
    t.className = "leo-toast leo-toast-in";

    const palette = {
      success: { bg: "rgba(0,255,157,0.08)",  bd: "rgba(0,255,157,0.35)",  fg: "#00ff9d" },
      error:   { bg: "rgba(255,77,109,0.08)", bd: "rgba(255,77,109,0.35)", fg: "#ff4d6d" },
      info:    { bg: "rgba(59,130,246,0.08)", bd: "rgba(59,130,246,0.35)", fg: "#93c5fd" },
    };
    const p = palette[kind] || palette.info;

    t.style.cssText = [
      `background: ${p.bg}`,
      `border: 1px solid ${p.bd}`,
      `color: ${p.fg}`,
      "padding: 10px 14px",
      "border-radius: 8px",
      "font-size: 13px",
      "backdrop-filter: blur(6px)",
      "pointer-events: auto",
      "font-family: 'IBM Plex Sans', sans-serif",
    ].join(";");

    t.textContent = String(message);
    container.appendChild(t);

    setTimeout(() => {
      t.classList.remove("leo-toast-in");
      t.classList.add("leo-toast-out");
      setTimeout(() => t.remove(), 300);
    }, 4000);
  }

  global.LeoAnim = {
    flashValue: flashValue,
    fadeIn: fadeIn,
    fadeOut: fadeOut,
    tickRow: tickRow,
    parseNumber: parseNumber,
    toast: toast,
  };
})(window);
