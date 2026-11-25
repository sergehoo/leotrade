/**
 * leo_assistant.js — Panel IA conversationnel Lyneci AI
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
  const WELCOME_MSG = "Bonjour ! Je suis **Lyneci AI**, votre copilote de trading.\n\nJe peux :\n• Analyser vos opportunités et positions\n• Calculer votre exposition et taille de position\n• Expliquer les scores et décisions du moteur IA\n• Vous avertir sur les risques\n\nComment puis-je vous aider ?";

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
    quota: null,            // ← snapshot du quota courant
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
      setStatus("connected", "Lyneci AI connecté");
    };

    state.ws.onmessage = (event) => {
      try {
        handleServerMessage(JSON.parse(event.data));
      } catch (e) {
        console.warn("[Lyneci AI] parse error", e);
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
          // La génération continue côté serveur : on garde la bulle telle
          // quelle, les chunks manquants seront resynchronisés au "done"
          // (clean_content) ou au rechargement de l'historique.
          bubble.innerHTML = renderMarkdown(stripActionMarkers(bubble.dataset.raw || ""));
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

      case "session": {
        const switched = state.sessionId && data.session_id !== state.sessionId;
        state.sessionId = data.session_id;
        if (data.quota) updateQuotaUI(data.quota);
        // Recharge l'historique : à la première connexion OU quand on bascule
        // sur une autre conversation (contexte métier, reprise depuis le centre).
        if (!state.historyLoaded || switched) {
          state.historyLoaded = true;
          if (data.history && data.history.length) {
            renderHistory(data.history);
          } else {
            clearMessages();
            appendWelcome();
          }
        }
        break;
      }

      case "user_saved":
        // Accusé de réception : le message utilisateur est persisté en base.
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

      case "chunk": {
        state.isThinking = false;
        // Dédup à la reconnexion : si la bulle (rechargée depuis l'historique)
        // contient déjà ce texte, on ignore le chunk en retard.
        if (typeof data.acc_len === "number") {
          const bubble = document.querySelector(`[data-msg-id="${data.id}"]`);
          const currentLen = bubble && bubble.dataset.raw ? bubble.dataset.raw.length : 0;
          if (currentLen >= data.acc_len) break;
        }
        appendChunk(data.id, data.text);
        break;
      }

      case "done":
        state.isThinking = false;
        state.streamComplete = true;
        setSendDisabled(false);
        state.currentMsgId = null;
        if (data.quota) updateQuotaUI(data.quota);

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

        if (data.action_request) {
          renderActionRequestCard(data.id, data.action_request);
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

      case "quota_exceeded":
        removeThinking();
        setSendDisabled(false);
        state.isThinking = false;
        if (data.quota) updateQuotaUI(data.quota);
        showQuotaModal(data.quota, data.plans || []);
        break;

      case "quota_updated":
        if (data.quota) updateQuotaUI(data.quota);
        hideQuotaModal();
        appendAssistantBubble("quota_ok_" + Date.now(), data.message || "✅ Quota rechargé !");
        setSendDisabled(false);
        break;

      case "quota_stripe_url":
        // Ouvrir le lien de paiement Stripe dans un nouvel onglet
        if (data.url) window.open(data.url, "_blank", "noopener");
        break;

      case "quota_payment_failed":
        appendErrorMsg(data.error || "Paiement échoué.");
        break;

      case "error":
        removeThinking();
        setSendDisabled(false);
        appendErrorMsg(data.message || "Erreur inconnue");
        break;
    }
  }

  // ── Rendu des messages ────────────────────────────────────────────────────

  function clearMessages() {
    if (els.messages) els.messages.innerHTML = "";
  }

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
        // Le contenu est TOUJOURS conservé en base (sauvegarde progressive).
        // PARTIAL = génération encore en cours (elle se poursuit côté serveur),
        // FAILED  = moteur IA interrompu, contenu partiel conservé.
        let displayContent = m.content;
        if (m.status === "PARTIAL") {
          displayContent = (m.content || "") + "\n\n*⏳ Génération en cours côté serveur…*";
        } else if (m.status === "FAILED" && !m.content) {
          displayContent = "*Le moteur IA n'a pas pu répondre — réessaie.*";
        }
        appendAssistantBubble(m.id, displayContent, m.created_at);
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

  // ── Carte de demande d'action (confirmation transactionnelle) ────────────
  // Badge PAPER/LIVE, verdict Risk Engine, boutons Confirmer / Annuler.
  // La confirmation passe par le backend (AssistantActionRequest) — double
  // confirmation exigée en LIVE.
  function renderActionRequestCard(msgId, req) {
    if (!els.messages || !req) return;

    // Mise à jour d'une carte existante (changement de statut)
    const existing = document.querySelector(`[data-action-request-id="${req.id}"]`);
    const isFinal = ["EXECUTED", "CANCELLED", "FAILED", "EXPIRED"].includes(req.status);

    const live = req.mode === "LIVE";
    const modeBadge = live
      ? '<span class="leo-ai-req-badge leo-ai-req-live">LIVE — ARGENT RÉEL</span>'
      : '<span class="leo-ai-req-badge leo-ai-req-paper">PAPER</span>';
    const risk = req.risk_summary || {};
    const riskBadge = risk.decision
      ? `<span class="leo-ai-req-badge ${risk.decision === "APPROVE" ? "leo-ai-req-risk-ok" : "leo-ai-req-risk-ko"}">Risk : ${escapeHtml(risk.decision)}</span>`
      : "";
    const statusLabel = {
      WAITING_CONFIRMATION: live ? "⏳ En attente de DOUBLE confirmation" : "⏳ En attente de confirmation",
      CONFIRMED: "⚠ 1/2 confirmations — confirme encore une fois",
      EXECUTED: "✅ Exécutée",
      CANCELLED: "✕ Annulée",
      FAILED: "⚠ Échec",
      EXPIRED: "⌛ Expirée",
    }[req.status] || req.status;

    const buttons = isFinal ? "" : `
      <div class="leo-ai-req-buttons">
        <button class="leo-ai-req-confirm" data-req-confirm="${req.id}">
          ${req.status === "CONFIRMED" ? "Confirmer (2/2)" : "✓ Confirmer"}
        </button>
        <button class="leo-ai-req-cancel" data-req-cancel="${req.id}">✕ Annuler</button>
      </div>`;

    const html = `
      <div class="leo-ai-req-head">${modeBadge}${riskBadge}
        <span class="leo-ai-req-status">${statusLabel}</span>
      </div>
      ${req.error_message ? `<div class="leo-ai-req-error">${escapeHtml(req.error_message)}</div>` : ""}
      ${buttons}`;

    let card = existing;
    if (!card) {
      card = document.createElement("div");
      card.className = "leo-ai-action-card leo-ai-req-card";
      card.dataset.actionRequestId = req.id;
      const bubble = document.querySelector(`[data-msg-id="${msgId}"]`);
      const wrapper = bubble ? bubble.closest(".leo-ai-msg") : null;
      (wrapper || els.messages).appendChild(card);
    }
    card.innerHTML = html;

    card.querySelectorAll("[data-req-confirm]").forEach((b) =>
      b.addEventListener("click", () =>
        send({type: "action_request_confirm", request_id: req.id})));
    card.querySelectorAll("[data-req-cancel]").forEach((b) =>
      b.addEventListener("click", () =>
        send({type: "action_request_cancel", request_id: req.id})));

    scrollToBottom();
  }

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
    // Tente d'ouvrir le formulaire d'ordre existant de Lyneci
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

  // ── Quota UI ──────────────────────────────────────────────────────────────

  function updateQuotaUI(quota) {
    state.quota = quota;
    const bar  = $("leo-ai-quota-bar");
    const fill = $("leo-ai-quota-fill");
    const cnt  = $("leo-ai-quota-count");
    const lbl  = $("leo-ai-quota-label");
    if (!bar) return;

    bar.style.display = "";
    const pct = quota.pct || 0;
    fill.style.width = pct + "%";
    cnt.textContent  = `${quota.used}/${quota.limit}`;
    lbl.textContent  = quota.plan_label || quota.plan;

    // Couleur selon saturation
    const cls = pct >= 90 ? "critical" : pct >= 70 ? "warning" : "";
    fill.className = "leo-ai-quota-fill" + (cls ? " " + cls : "");
    cnt.className  = "leo-ai-quota-count"  + (cls ? " " + cls : "");
  }

  function showQuotaModal(quota, plans) {
    const modal     = $("leo-ai-quota-modal");
    const desc      = $("leo-ai-quota-modal-desc");
    const plansEl   = $("leo-ai-quota-plans");
    if (!modal) return;

    if (desc) desc.textContent =
      `Vous avez utilisé vos ${quota ? quota.limit : ""} messages IA disponibles (plan ${quota ? quota.plan_label : ""}).`;

    if (plansEl) {
      plansEl.innerHTML = "";
      plans.forEach(plan => {
        const card = document.createElement("div");
        card.className = "leo-ai-quota-plan-card";
        card.innerHTML = `
          <div class="leo-ai-quota-plan-name">${escapeHtml(plan.label)}</div>
          <div class="leo-ai-quota-plan-detail">${plan.messages} messages · $${plan.price_usd}</div>
          <div class="leo-ai-quota-plan-btns">
            <button class="leo-ai-quota-btn-wallet" data-plan="${escapeHtml(plan.plan)}"
                    onclick="LeoAssistant.payWallet('${escapeHtml(plan.plan)}')">
              💳 Wallet Lyneci
            </button>
            <button class="leo-ai-quota-btn-stripe" data-plan="${escapeHtml(plan.plan)}"
                    onclick="LeoAssistant.payStripe('${escapeHtml(plan.plan)}')">
              📱 Paystack / Mobile Money
            </button>
          </div>
        `;
        plansEl.appendChild(card);
      });
    }
    modal.style.display = "";
  }

  function hideQuotaModal() {
    const modal = $("leo-ai-quota-modal");
    if (modal) modal.style.display = "none";
  }

  function payWallet(plan) {
    // Remplacer les boutons par un indicateur de chargement
    const plansEl = $("leo-ai-quota-plans");
    if (plansEl) {
      plansEl.innerHTML = `<div class="leo-ai-quota-paying">⏳ Paiement en cours via wallet…</div>`;
    }
    send({ type: "quota_pay_wallet", plan });
  }

  function payStripe(plan) {
    const plansEl = $("leo-ai-quota-plans");
    if (plansEl) {
      plansEl.innerHTML = `<div class="leo-ai-quota-paying">📱 Redirection vers Paystack / Mobile Money…</div>`;
    }
    send({ type: "quota_pay_stripe", plan });
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

  // ── Rendu Markdown riche ───────────────────────────────────────────────────
  // Titres (#/##/###), tableaux (| a | b |), listes (puces + numérotées),
  // citations (>), séparateurs (---), surlignage (==texte==), gras, italique,
  // code, liens internes et images internes (/static/, /media/).
  // L'entrée est systématiquement échappée avant tout parsing (anti-XSS).

  function renderInline(s) {
    // Images : uniquement des ressources internes
    s = s.replace(/!\[([^\]]*)\]\((\/(?:static|media)\/[^\s)]+)\)/g,
      '<img class="leo-ai-img" src="$2" alt="$1" loading="lazy">');
    // Liens : chemins internes ou ancres uniquement
    s = s.replace(/\[([^\]]+)\]\((\/[^\s)]*|#[^\s)]*)\)/g,
      '<a class="leo-ai-link" href="$2">$1</a>');
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/==([^=\n]+)==/g, '<mark>$1</mark>');
    return s;
  }

  function renderMarkdown(text) {
    if (!text) return "";
    const lines = escapeHtml(text).split("\n");
    const out = [];
    let list = null;        // "ul" | "ol" | null
    let tableRows = null;   // lignes de tableau accumulées
    let para = [];

    const isTableSep = (line) => /^\s*\|?[\s:\-|]+\|?\s*$/.test(line) && line.includes("-");

    function closePara() {
      if (para.length) {
        out.push('<p>' + para.join('<br>') + '</p>');
        para = [];
      }
    }
    function closeList() {
      if (list) { out.push(`</${list}>`); list = null; }
    }
    function closeTable() {
      if (!tableRows) return;
      const rows = tableRows;
      tableRows = null;
      if (!rows.length) return;
      const toCells = (line) =>
        line.replace(/^\s*\||\|\s*$/g, "").split("|").map(c => renderInline(c.trim()));
      let html = '<div class="leo-ai-table-wrap"><table class="leo-ai-table">';
      let start = 0;
      if (rows.length > 1 && isTableSep(rows[1])) {
        html += '<thead><tr>' + toCells(rows[0]).map(c => `<th>${c}</th>`).join('') + '</tr></thead>';
        start = 2;
      }
      html += '<tbody>';
      for (let i = start; i < rows.length; i++) {
        if (isTableSep(rows[i])) continue;
        html += '<tr>' + toCells(rows[i]).map(c => `<td>${c}</td>`).join('') + '</tr>';
      }
      html += '</tbody></table></div>';
      out.push(html);
    }
    function closeAll() { closePara(); closeList(); closeTable(); }

    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");

      // Tableau : la ligne commence et finit par |
      if (/^\s*\|.*\|\s*$/.test(line)) {
        closePara(); closeList();
        (tableRows = tableRows || []).push(line.trim());
        continue;
      }
      if (tableRows) closeTable();

      // Ligne vide → fin de bloc
      if (!line.trim()) { closeAll(); continue; }

      // Séparateur horizontal (---, ***, ___, ⸻, ━━━, ───)
      if (/^\s*([-*_]\s*){3,}$/.test(line) || /^[⸻━─]+$/.test(line.trim())) {
        closeAll(); out.push('<hr class="leo-ai-hr">'); continue;
      }

      // Titres markdown
      const h = line.match(/^(#{1,6})\s+(.+)$/);
      if (h) {
        closeAll();
        const level = Math.min(h[1].length, 3);
        out.push(`<div class="leo-ai-h${level}">${renderInline(h[2])}</div>`);
        continue;
      }
      // **Titre** seul sur sa ligne (rétro-compatibilité)
      const bt = line.match(/^\*\*([^*]+)\*\*:?\s*$/);
      if (bt) {
        closeAll();
        out.push(`<div class="leo-ai-section-title">${renderInline(bt[1])}</div>`);
        continue;
      }

      // Citation (le ">" est déjà échappé en &gt;)
      const q = line.match(/^&gt;\s?(.*)$/);
      if (q) {
        closePara(); closeList();
        out.push(`<blockquote class="leo-ai-quote">${renderInline(q[1])}</blockquote>`);
        continue;
      }

      // Listes à puces / numérotées
      const ul = line.match(/^\s*[•\-*]\s+(.+)$/);
      const ol = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
      if (ul || ol) {
        closePara(); closeTable();
        const kind = ul ? "ul" : "ol";
        if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${renderInline(ul ? ul[1] : ol[2])}</li>`);
        continue;
      }
      closeList();

      // Texte courant
      para.push(renderInline(line));
    }
    closeAll();
    return out.join("");
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

  function openConversation(conversationId) {
    open();
    const trySend = () => {
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({type: "select_conversation", id: conversationId}));
      } else {
        setTimeout(trySend, 400);
      }
    };
    trySend();
  }

  window.LeoAssistant = {
    open,
    close,
    toggle,
    openConversation,
    sendMessage,
    confirmAction,
    rejectAction,
    explainOpportunity,
    updatePageContext,
    payWallet,
    payStripe,
    isOpen: () => state.isOpen,
  };

  // Reprise depuis le centre des conversations : ?assistant_conversation=<id>
  function maybeOpenFromUrl() {
    try {
      const id = new URLSearchParams(window.location.search).get("assistant_conversation");
      if (id) openConversation(parseInt(id, 10));
    } catch (e) { /* noop */ }
  }
  setTimeout(maybeOpenFromUrl, 600);

  // Init au DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})(window);
