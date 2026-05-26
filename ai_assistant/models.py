"""
ai_assistant/models.py
======================

Modèles de données pour le panel IA conversationnel.

• AssistantSession  — session de conversation par user + contexte page
• AssistantMessage  — message (user ou assistant) avec snapshot de contexte
• AssistantAction   — action proposée par l'IA, en attente de confirmation
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class AssistantSession(models.Model):
    """
    Une session de conversation. Une session par user est ouverte à la fois ;
    un nouveau contexte de page crée un nouveau thread dans la même session.
    """
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
    page_context = models.CharField(
        max_length=100, default="dashboard", db_index=True,
        help_text="Page d'origine : dashboard, opportunities, positions…",
    )
    meta = models.JSONField(
        default=dict, blank=True,
        help_text="Contexte arbitraire : opportunity_id, position_id, etc.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"Session#{self.pk} {self.user} [{self.page_context}]"


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
        (ROLE_ASSISTANT, "LeoAI"),
        (ROLE_SYSTEM, "Système"),
    ]

    session = models.ForeignKey(
        AssistantSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    content = models.TextField()

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

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


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

    # Types d'actions autorisées dans le périmètre LeoTrade
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
