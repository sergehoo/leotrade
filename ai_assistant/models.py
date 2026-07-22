"""
ai_assistant/models.py
======================

Modèles de données pour le panel IA conversationnel.

• AssistantConversation — conversation persistante par contexte métier
• AssistantMessage  — message (user ou assistant) avec snapshot de contexte
• AssistantAction   — action proposée par l'IA, en attente de confirmation
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class AssistantConversation(models.Model):
    """
    Une conversation persistante, attachée à un contexte métier.

    Chaque contexte (trade idea #145, position #25, portefeuille, assistant
    général…) possède son historique indépendant. Aucune conversation n'est
    perdue : refresh, reconnexion WS et redémarrage serveur rechargent
    l'historique depuis PostgreSQL.
    """

    CONTEXT_GENERAL = "GENERAL"
    CONTEXT_DASHBOARD = "DASHBOARD"
    CONTEXT_TRADE_IDEA = "TRADE_IDEA"
    CONTEXT_POSITION = "POSITION"
    CONTEXT_ORDER = "ORDER"
    CONTEXT_PORTFOLIO = "PORTFOLIO"
    CONTEXT_BROKER = "BROKER"
    CONTEXT_SIGNAL = "SIGNAL"
    CONTEXT_OPPORTUNITY = "OPPORTUNITY"
    CONTEXT_CHOICES = [
        (CONTEXT_GENERAL, "Assistant général"),
        (CONTEXT_DASHBOARD, "Dashboard"),
        (CONTEXT_TRADE_IDEA, "Trade Idea"),
        (CONTEXT_POSITION, "Position"),
        (CONTEXT_ORDER, "Ordre"),
        (CONTEXT_PORTFOLIO, "Portefeuille"),
        (CONTEXT_BROKER, "Broker"),
        (CONTEXT_SIGNAL, "Signal"),
        (CONTEXT_OPPORTUNITY, "Opportunité IA"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_sessions",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="assistant_sessions",
    )

    title = models.CharField(
        max_length=200, blank=True,
        help_text="Auto-généré depuis le premier message si vide.",
    )
    context_type = models.CharField(
        max_length=20, choices=CONTEXT_CHOICES,
        default=CONTEXT_GENERAL, db_index=True,
    )
    context_id = models.PositiveIntegerField(
        null=True, blank=True, db_index=True,
        help_text="ID de l'objet métier (trade idea, position…).",
    )

    page_context = models.CharField(
        max_length=100, default="dashboard", db_index=True,
        help_text="Page d'origine : dashboard, opportunities, positions…",
    )
    meta = models.JSONField(
        default=dict, blank=True,
        help_text="Contexte arbitraire : opportunity_id, position_id, etc.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "context_type", "context_id"]),
            models.Index(fields=["user", "archived", "-updated_at"]),
        ]

    def __str__(self):
        return f"Conversation#{self.pk} {self.user} [{self.context_label}]"

    @property
    def context_label(self) -> str:
        label = self.get_context_type_display()
        return f"{label} #{self.context_id}" if self.context_id else label

    def ensure_title(self, first_message: str = ""):
        if self.title:
            return
        base = (first_message or "").strip().replace("\n", " ")
        self.title = (base[:80] + "…") if len(base) > 80 else (base or self.context_label)
        self.save(update_fields=["title", "updated_at"])


class AssistantMessage(models.Model):
    """
    Un message dans une session. role = USER | ASSISTANT | SYSTEM.
    Les messages ASSISTANT embarquent les méta-données provider/tokens.
    """
    ROLE_USER = "USER"
    ROLE_ASSISTANT = "ASSISTANT"
    ROLE_SYSTEM = "SYSTEM"
    ROLE_CHOICES = [
        (ROLE_USER, "Utilisateur"),
        (ROLE_ASSISTANT, "Lyneci AI"),
        (ROLE_SYSTEM, "Système"),
    ]

    STATUS_SAVED = "SAVED"
    STATUS_PARTIAL = "PARTIAL"     # génération en cours ou interrompue — contenu conservé
    STATUS_FAILED = "FAILED"       # le moteur IA a échoué — contenu partiel conservé
    STATUS_CHOICES = [
        (STATUS_SAVED, "Sauvegardé"),
        (STATUS_PARTIAL, "Partiel"),
        (STATUS_FAILED, "Échec"),
    ]

    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    content = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default=STATUS_SAVED, db_index=True,
    )
    error_message = models.TextField(blank=True)

    # Snapshot live au moment du message (portefeuille, risque, marché)
    context_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Snapshot live injecté dans le prompt.",
    )

    # Méta provider
    provider = models.CharField(max_length=50, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    latency_ms = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


class AssistantConversationParticipant(models.Model):
    """Participant d'une conversation — prépare le futur mode équipe.

    Aujourd'hui chaque conversation n'a que son propriétaire ; ce modèle
    permettra d'inviter des membres (lecture seule ou contribution).
    """

    ROLE_OWNER = "OWNER"
    ROLE_MEMBER = "MEMBER"
    ROLE_VIEWER = "VIEWER"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Propriétaire"),
        (ROLE_MEMBER, "Membre"),
        (ROLE_VIEWER, "Lecture seule"),
    ]

    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="assistant_participations",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_OWNER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("conversation", "user")]

    def __str__(self):
        return f"{self.user} → conv#{self.conversation_id} [{self.role}]"


class AssistantAttachment(models.Model):
    """Pièce jointe de conversation — prépare l'upload de documents."""

    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name="attachments",
    )
    message = models.ForeignKey(
        "AssistantMessage", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="attachments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="assistant_attachments",
    )
    file = models.FileField(upload_to="assistant/attachments/%Y/%m/")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} (conv#{self.conversation_id})"


class AssistantAction(models.Model):
    """
    Action proposée par l'IA. Nécessite confirmation explicite de l'utilisateur
    avant toute exécution. Audit complet (qui, quand, résultat).
    """
    STATUS_PROPOSED = "PROPOSED"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_REJECTED = "REJECTED"
    STATUS_EXECUTED = "EXECUTED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Proposée"),
        (STATUS_CONFIRMED, "Confirmée"),
        (STATUS_REJECTED, "Rejetée"),
        (STATUS_EXECUTED, "Exécutée"),
        (STATUS_FAILED, "Échec"),
    ]

    # Types d'actions autorisées dans le périmètre Lyneci
    TYPE_DRAFT_ORDER = "DRAFT_ORDER"       # prépare un formulaire d'ordre
    TYPE_ADJUST_SL = "ADJUST_SL"          # suggère un stop-loss
    TYPE_ADJUST_TP = "ADJUST_TP"          # suggère un take-profit
    TYPE_SUGGEST_SIZE = "SUGGEST_SIZE"    # suggère une taille de position
    TYPE_OPEN_MODAL = "OPEN_MODAL"        # ouvre une modal UI
    TYPE_INFO = "INFO"                    # information sans action broker
    ACTION_TYPE_CHOICES = [
        (TYPE_DRAFT_ORDER, "Brouillon d'ordre"),
        (TYPE_ADJUST_SL, "Ajuster Stop Loss"),
        (TYPE_ADJUST_TP, "Ajuster Take Profit"),
        (TYPE_SUGGEST_SIZE, "Suggérer taille"),
        (TYPE_OPEN_MODAL, "Ouvrir modal"),
        (TYPE_INFO, "Information"),
    ]

    message = models.ForeignKey(
        AssistantMessage,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action_type = models.CharField(max_length=50, choices=ACTION_TYPE_CHOICES)
    parameters = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PROPOSED, db_index=True,
    )
    rationale = models.TextField(blank=True)

    # Audit trail
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def confirm(self):
        self.status = self.STATUS_CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_at", "updated_at"])

    def reject(self):
        self.status = self.STATUS_REJECTED
        self.rejected_at = timezone.now()
        self.save(update_fields=["status", "rejected_at", "updated_at"])

    def mark_executed(self, result: dict):
        self.status = self.STATUS_EXECUTED
        self.executed_at = timezone.now()
        self.result = result
        self.save(update_fields=["status", "executed_at", "result", "updated_at"])

    def mark_failed(self, error: str):
        self.status = self.STATUS_FAILED
        self.error_message = error
        self.save(update_fields=["status", "error_message", "updated_at"])

    def __str__(self):
        return f"Action#{self.pk} {self.action_type} [{self.status}]"


# ── Quota & billing ─────────────────────────────────────────────────────────

class AIUserQuota(models.Model):
    """
    Quota d'utilisation de Lyneci AI par utilisateur.

    Plans :
      FREE  — 20 messages offerts (réinitialisés chaque mois)
      BASIC — $5  → 200 messages
      PRO   — $20 → 1 000 messages
      UNLIMITED — admin / partenaire, pas de limite
    """
    PLAN_FREE      = "FREE"
    PLAN_BASIC     = "BASIC"
    PLAN_PRO       = "PRO"
    PLAN_UNLIMITED = "UNLIMITED"
    PLAN_CHOICES = [
        (PLAN_FREE,      "Gratuit (20 msg/mois)"),
        (PLAN_BASIC,     "Basic — $5 / 200 messages"),
        (PLAN_PRO,       "Pro — $20 / 1 000 messages"),
        (PLAN_UNLIMITED, "Illimité"),
    ]

    PLAN_LIMITS = {
        PLAN_FREE:      20,
        PLAN_BASIC:     200,
        PLAN_PRO:       1_000,
        PLAN_UNLIMITED: 999_999,
    }
    PLAN_PRICES_USD = {
        PLAN_FREE:      Decimal("0.00"),
        PLAN_BASIC:     Decimal("5.00"),
        PLAN_PRO:       Decimal("20.00"),
        PLAN_UNLIMITED: Decimal("0.00"),
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_quota",
    )
    plan = models.CharField(
        max_length=20, choices=PLAN_CHOICES, default=PLAN_FREE,
    )
    messages_used = models.IntegerField(default=0)
    messages_limit = models.IntegerField(
        default=20,
        help_text="Nombre max de messages sur la période actuelle.",
    )
    # Dépenses cumulées (historique)
    total_spent_usd = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )
    # Période courante
    period_start = models.DateTimeField(default=timezone.now)
    period_end   = models.DateTimeField(null=True, blank=True)

    # État
    is_suspended = models.BooleanField(
        default=False,
        help_text="Bloqué manuellement par un admin.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @property
    def remaining(self) -> int:
        return max(0, self.messages_limit - self.messages_used)

    @property
    def is_exhausted(self) -> bool:
        if self.plan == self.PLAN_UNLIMITED:
            return False
        return self.messages_used >= self.messages_limit

    @property
    def usage_pct(self) -> int:
        if self.messages_limit == 0:
            return 100
        return min(100, int(self.messages_used * 100 / self.messages_limit))

    def consume(self, n: int = 1):
        """Décrémenter le compteur (appelé après chaque message IA réussi)."""
        self.messages_used += n
        self.save(update_fields=["messages_used", "updated_at"])

    def top_up(self, plan: str):
        """
        Passer à un plan supérieur ou recharger le plan courant.
        Réinitialise le compteur et met à jour la limite.
        """
        from django.utils import timezone as tz
        self.plan = plan
        self.messages_used = 0
        self.messages_limit = self.PLAN_LIMITS[plan]
        self.total_spent_usd += self.PLAN_PRICES_USD[plan]
        self.period_start = tz.now()
        self.period_end = None
        self.save(update_fields=[
            "plan", "messages_used", "messages_limit",
            "total_spent_usd", "period_start", "period_end", "updated_at",
        ])

    def monthly_reset(self):
        """Réinitialise le plan FREE chaque mois."""
        if self.plan == self.PLAN_FREE:
            self.messages_used = 0
            self.period_start = timezone.now()
            self.save(update_fields=["messages_used", "period_start", "updated_at"])

    def __str__(self):
        return f"Quota {self.user} [{self.plan}] {self.messages_used}/{self.messages_limit}"


class AIQuotaPayment(models.Model):
    """
    Trace chaque paiement pour l'extension du quota.
    Méthode : WALLET (débit direct) ou STRIPE (lien externe).
    """
    METHOD_WALLET = "WALLET"
    METHOD_STRIPE = "STRIPE"
    METHOD_CHOICES = [
        (METHOD_WALLET, "Portefeuille Lyneci"),
        (METHOD_STRIPE, "Stripe (carte / lien)"),
    ]
    STATUS_PENDING   = "PENDING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED    = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING,   "En attente"),
        (STATUS_COMPLETED, "Complété"),
        (STATUS_FAILED,    "Échoué"),
    ]

    quota   = models.ForeignKey(AIUserQuota, on_delete=models.CASCADE, related_name="payments")
    plan    = models.CharField(max_length=20)
    amount_usd = models.DecimalField(max_digits=10, decimal_places=2)
    method  = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status  = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Stripe
    stripe_session_id  = models.CharField(max_length=200, blank=True)
    stripe_payment_url = models.TextField(blank=True)
    # Audit
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment#{self.pk} {self.quota.user} {self.plan} ${self.amount_usd} [{self.status}]"


class AssistantActionRequest(models.Model):
    """
    Confirmation transactionnelle des actions de l'assistant.

    Règle absolue : l'assistant ne déclenche JAMAIS une action sensible sur
    un simple texte. Il crée une AssistantActionRequest (résumé + analyse
    risque), l'utilisateur confirme explicitement (token), et seulement
    alors l'exécution passe par les services backend + Risk Engine.
    En mode LIVE : DOUBLE confirmation obligatoire.
    """

    STATUS_DRAFT = "DRAFT"
    STATUS_WAITING = "WAITING_CONFIRMATION"
    STATUS_CONFIRMED = "CONFIRMED"          # 1re confirmation reçue (LIVE : en attend une 2e)
    STATUS_EXECUTED = "EXECUTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_FAILED = "FAILED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Brouillon"),
        (STATUS_WAITING, "En attente de confirmation"),
        (STATUS_CONFIRMED, "Confirmée"),
        (STATUS_EXECUTED, "Exécutée"),
        (STATUS_CANCELLED, "Annulée"),
        (STATUS_FAILED, "Échec"),
        (STATUS_EXPIRED, "Expirée"),
    ]

    ACTION_CHOICES = [
        ("EXECUTE_TRADE_IDEA", "Exécuter une trade idea"),
        ("PREPARE_TRADE", "Préparer un trade"),
        ("APPROVE_TRADE_IDEA", "Approuver une trade idea"),
        ("REJECT_TRADE_IDEA", "Rejeter une trade idea"),
        ("CANCEL_ORDER", "Annuler un ordre"),
        ("CLOSE_POSITION", "Fermer une position"),
        ("REDUCE_POSITION", "Réduire une position"),
        ("SYNC_PORTFOLIO", "Synchroniser le portefeuille"),
        ("TEST_BROKER", "Tester la connexion broker"),
        ("ACTIVATE_KILL_SWITCH", "Activer le kill switch"),
        ("DEACTIVATE_KILL_SWITCH", "Désactiver le kill switch"),
        ("DISABLE_AUTO_TRADING", "Désactiver l'auto-trading"),
        ("ENABLE_AUTO_TRADING", "Activer l'auto-trading"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="assistant_action_requests",
    )
    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE,
        related_name="action_requests",
    )
    message = models.ForeignKey(
        "AssistantMessage", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="action_requests",
    )

    intent = models.CharField(max_length=40, blank=True, db_index=True)
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES, db_index=True)
    status = models.CharField(
        max_length=25, choices=STATUS_CHOICES,
        default=STATUS_WAITING, db_index=True,
    )

    # Cible métier (TradeIdea, Order, Position, Portfolio, BrokerAccount…)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)

    # Mode d'exécution au moment de la préparation (badge UI + double confirm)
    mode = models.CharField(max_length=10, default="PAPER", db_index=True)
    requires_double_confirmation = models.BooleanField(default=False)
    confirmations_received = models.PositiveSmallIntegerField(default=0)

    summary = models.TextField(help_text="Résumé lisible présenté avant confirmation.")
    risk_summary = models.JSONField(
        default=dict, blank=True,
        help_text="Sortie du Risk Engine : décision, stake approuvé, blocages.",
    )
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    confirmation_token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["conversation", "status"]),
        ]

    def __str__(self):
        return f"ActionRequest#{self.pk} {self.action_type} [{self.status}]"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_actionable(self) -> bool:
        return (
            self.status in (self.STATUS_WAITING, self.STATUS_CONFIRMED)
            and not self.is_expired
        )
