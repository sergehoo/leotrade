"""
Phase IA — création de la table AIDecisionLog.
"""

from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portfolio", "0001_initial"),
        ("trading", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIDecisionLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("symbol", models.CharField(blank=True, db_index=True, max_length=50)),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("CLAUDE", "Anthropic Claude API"),
                            ("OLLAMA", "Ollama local LLM"),
                            ("HEURISTIC", "Heuristic fallback"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                (
                    "model_name",
                    models.CharField(
                        blank=True,
                        help_text="ex: claude-opus-4-5, llama3:70b",
                        max_length=120,
                    ),
                ),
                ("fallback_used", models.BooleanField(db_index=True, default=False)),
                ("fallback_reason", models.CharField(blank=True, max_length=200)),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("EXECUTE", "Execute"),
                            ("PLAN", "Plan / waitlist"),
                            ("WATCH", "Watch only"),
                            ("REJECT", "Reject"),
                            ("ABSTAIN", "No clear signal"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("confidence", models.FloatField(default=0.0, help_text="0.0 → 1.0")),
                (
                    "expected_rr",
                    models.FloatField(blank=True, help_text="Risk:Reward attendu", null=True),
                ),
                (
                    "suggested_stake",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                (
                    "suggested_stop_loss",
                    models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True),
                ),
                (
                    "suggested_take_profit",
                    models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True),
                ),
                (
                    "rationale",
                    models.TextField(blank=True, help_text="Explication libre fournie par le LLM"),
                ),
                (
                    "risks",
                    models.JSONField(blank=True, default=list, help_text="Liste de risques identifiés"),
                ),
                (
                    "prompt_inputs",
                    models.JSONField(
                        blank=True, default=dict, help_text="Features + contexte envoyés"
                    ),
                ),
                (
                    "raw_response",
                    models.JSONField(
                        blank=True, default=dict, help_text="Réponse brute du provider"
                    ),
                ),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("tokens_in", models.PositiveIntegerField(default=0)),
                ("tokens_out", models.PositiveIntegerField(default=0)),
                (
                    "cost_usd",
                    models.DecimalField(
                        decimal_places=6,
                        default=Decimal("0"),
                        help_text="Coût estimé",
                        max_digits=10,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "portfolio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_decisions",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "trade_idea",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_decisions",
                        to="trading.tradeidea",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_decisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="aidecisionlog",
            index=models.Index(
                fields=["provider", "created_at"], name="ai_engine_a_provid_4f8c2a_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="aidecisionlog",
            index=models.Index(fields=["symbol", "decision"], name="ai_engine_a_symbol_b1d3e7_idx"),
        ),
        migrations.AddIndex(
            model_name="aidecisionlog",
            index=models.Index(
                fields=["user", "created_at"], name="ai_engine_a_user_id_99cf08_idx"
            ),
        ),
    ]
