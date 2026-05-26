"""
risk/migrations/0003_riskoverrideaudit.py
==========================================

Crée la table risk_riskoverrideaudit.

Pour appliquer :
    python manage.py migrate risk
"""

from __future__ import annotations

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0002_initial"),
        ("portfolio", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RiskOverrideAudit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                # ── FKs ─────────────────────────────────────────────────────
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        help_text="Utilisateur qui a accepté la décharge.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="risk_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "portfolio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="risk_overrides",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "risk_decision",
                    models.ForeignKey(
                        blank=True,
                        help_text="Décision de risque associée (peut être nulle si non persistée).",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="overrides",
                        to="risk.riskdecision",
                    ),
                ),
                # ── Identité du trade ────────────────────────────────────────
                (
                    "symbol",
                    models.CharField(db_index=True, max_length=50),
                ),
                (
                    "side",
                    models.CharField(blank=True, max_length=10),
                ),
                (
                    "requested_stake",
                    models.DecimalField(
                        decimal_places=2,
                        default="0.00",
                        max_digits=18,
                    ),
                ),
                # ── Codes franchis ───────────────────────────────────────────
                (
                    "codes_bypassed",
                    models.JSONField(
                        default=list,
                        help_text='Liste des codes SOFT franchis, ex: ["MAX_OPEN_POSITIONS"].',
                    ),
                ),
                # ── Décharge ────────────────────────────────────────────────
                (
                    "reason",
                    models.TextField(
                        blank=True,
                        help_text="Motif saisi par l'utilisateur dans le formulaire de décharge.",
                    ),
                ),
                # ── Contexte réseau ──────────────────────────────────────────
                (
                    "ip_address",
                    models.GenericIPAddressField(
                        blank=True,
                        null=True,
                        help_text="IP de l'utilisateur au moment de l'override.",
                    ),
                ),
                (
                    "user_agent",
                    models.TextField(
                        blank=True,
                        help_text="User-Agent HTTP de l'utilisateur.",
                    ),
                ),
                # ── Horodatage ───────────────────────────────────────────────
                (
                    "overridden_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        help_text="Horodatage de la décharge (immutable).",
                    ),
                ),
                # ── Snapshot profil ──────────────────────────────────────────
                (
                    "profile_snapshot",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Snapshot des paramètres du RiskProfile au moment de l'override. "
                            "Permet de reconstituer le contexte si le profil évolue ensuite."
                        ),
                    ),
                ),
            ],
            options={
                "verbose_name": "Risk Override Audit",
                "verbose_name_plural": "Risk Override Audits",
                "ordering": ["-overridden_at"],
            },
        ),
        # ── Index ────────────────────────────────────────────────────────────
        migrations.AddIndex(
            model_name="riskoverrideaudit",
            index=models.Index(
                fields=["user", "overridden_at"],
                name="risk_overri_user_id_oat_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="riskoverrideaudit",
            index=models.Index(
                fields=["portfolio", "overridden_at"],
                name="risk_overri_pf_oat_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="riskoverrideaudit",
            index=models.Index(
                fields=["symbol", "overridden_at"],
                name="risk_overri_sym_oat_idx",
            ),
        ),
    ]
