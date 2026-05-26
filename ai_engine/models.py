"""
ai_engine/models.py
===================

Audit trail des décisions IA (LLM + heuristique). Indispensable pour :
  - le retraining (corréler décision ↔ outcome via TradeIdeaFeedback)
  - le debug / la conformité (qui a recommandé quoi, avec quelle entrée)
  - les rapports de performance par modèle

Aucune donnée sensible (token broker etc.) n'est stockée ici.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class AIDecisionLog(models.Model):
    """
    Journal d'une décision prise par AITradeAdvisor.
    """

    PROVIDER_CHOICES = [
        ("CLAUDE", "Anthropic Claude API"),
        ("OLLAMA", "Ollama local LLM"),
        ("HEURISTIC", "Heuristic fallback"),
    ]

    DECISION_CHOICES = [
        ("EXECUTE", "Execute"),
        ("PLAN", "Plan / waitlist"),
        ("WATCH", "Watch only"),
        ("REJECT", "Reject"),
        ("ABSTAIN", "No clear signal"),
    ]

    # Contexte
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ai_decisions",
    )
    portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ai_decisions",
    )
    trade_idea = models.ForeignKey(
        "trading.TradeIdea",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ai_decisions",
    )
    symbol = models.CharField(max_length=50, blank=True, db_index=True)

    # Provider qui a *vraiment* répondu (peut être différent du préféré si fallback)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)
    model_name = models.CharField(max_length=120, blank=True, help_text="ex: claude-opus-4-5, llama3:70b")
    fallback_used = models.BooleanField(default=False, db_index=True)
    fallback_reason = models.CharField(max_length=200, blank=True)

    # Décision
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, db_index=True)
    confidence = models.FloatField(default=0.0, help_text="0.0 → 1.0")
    expected_rr = models.FloatField(null=True, blank=True, help_text="Risk:Reward attendu")
    suggested_stake = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    suggested_stop_loss = models.DecimalField(
        max_digits=24, decimal_places=8, null=True, blank=True
    )
    suggested_take_profit = models.DecimalField(
        max_digits=24, decimal_places=8, null=True, blank=True
    )

    rationale = models.TextField(blank=True, help_text="Explication libre fournie par le LLM")
    risks = models.JSONField(default=list, blank=True, help_text="Liste de risques identifiés")

    # Audit trail
    prompt_inputs = models.JSONField(default=dict, blank=True, help_text="Features + contexte envoyés")
    raw_response = models.JSONField(default=dict, blank=True, help_text="Réponse brute du provider")
    latency_ms = models.PositiveIntegerField(default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0, help_text="Coût estimé")

    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "created_at"]),
            models.Index(fields=["symbol", "decision"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.symbol} → {self.decision} ({self.provider}, conf={self.confidence:.2f})"
