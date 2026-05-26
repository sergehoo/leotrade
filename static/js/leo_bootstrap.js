/* =============================================================================
 * leo_bootstrap.js — initialisation globale LeoTrade côté front
 * =============================================================================
 *
 * À charger APRÈS leo_websocket.js et leo_animations.js, AVANT les scripts
 * spécifiques aux pages (cockpit.js, etc.).
 *
 * Responsabilités :
 *   - Brancher les changements d'état WebSocket sur des toasts utilisateur
 *   - Désactiver les boutons submit pendant l'envoi du form (anti double-clic)
 *   - Forcer le respect de prefers-reduced-motion sur les animations CSS
 *
 * Aucune dépendance jQuery. Vanilla JS only.
 * ============================================================================= */

(function () {
  "use strict";

  // -------------------------------------------------------------------------
  // 1. Toast quand la connexion WS bascule
  // -------------------------------------------------------------------------
  if (window.LeoWS && typeof window.LeoWS.onStateChange === "function") {
    let lastState = "online";
    window.LeoWS.onStateChange(function (state) {
      if (!window.LeoAnim) return;
      if (state === lastState) return;

      if (state === "offline") {
        window.LeoAnim.toast("Connexion temps réel perdue. Tentatives de reconnexion en cours…", "error");
      } else if (state === "reconnecting" && lastState === "offline") {
        // déjà notifié, on évite le spam
      } else if (state === "online" && lastState !== "online") {
        window.LeoAnim.toast("Connexion temps réel rétablie.", "success");
      }
      lastState = state;
    });
  }

  // -------------------------------------------------------------------------
  // 2. Disable submit buttons pendant l'envoi (anti double-soumission)
  //    Ne s'applique pas si data-no-disable est présent sur le form ou bouton.
  // -------------------------------------------------------------------------
  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.noDisable === "true") return;

    const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach(function (btn) {
      if (btn.dataset.noDisable === "true") return;
      btn.disabled = true;
      btn.dataset.previousLabel = btn.textContent;
      // Petit indicateur visuel sur les <button>
      if (btn.tagName === "BUTTON" && btn.textContent.length > 0) {
        btn.textContent = "Envoi en cours…";
      }
      // Sécurité : si la soumission n'a pas redirigé en 10s, on réactive
      setTimeout(function () {
        if (document.body.contains(btn) && btn.disabled) {
          btn.disabled = false;
          if (btn.dataset.previousLabel) btn.textContent = btn.dataset.previousLabel;
        }
      }, 10_000);
    });
  });

  // -------------------------------------------------------------------------
  // 3. Burger menu mobile (toggle de la sidebar)
  //    Cherche un bouton [data-leo-burger] et la sidebar [data-leo-sidebar].
  // -------------------------------------------------------------------------
  document.addEventListener("click", function (event) {
    const burger = event.target.closest("[data-leo-burger]");
    if (!burger) return;
    const sidebar = document.querySelector("[data-leo-sidebar]");
    if (!sidebar) return;
    const isOpen = sidebar.classList.toggle("leo-sidebar-open");
    burger.setAttribute("aria-expanded", isOpen ? "true" : "false");
    document.body.classList.toggle("leo-sidebar-locked", isOpen);
  });

  // Fermeture sur Escape
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    const sidebar = document.querySelector("[data-leo-sidebar].leo-sidebar-open");
    if (!sidebar) return;
    sidebar.classList.remove("leo-sidebar-open");
    document.body.classList.remove("leo-sidebar-locked");
    const burger = document.querySelector("[data-leo-burger]");
    if (burger) burger.setAttribute("aria-expanded", "false");
  });
})();
