import csv
import json

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone

from .models import (
    DailyRiskState,
    KillSwitchEvent,
    RiskDecision,
    RiskOverrideAudit,
    RiskProfile,
    WeeklyRiskState,
)


@admin.register(RiskProfile)
class RiskProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "portfolio", "name", "is_active", "is_default",
        "max_risk_per_trade", "max_daily_loss", "max_weekly_loss",
        "max_drawdown", "max_open_positions", "allow_live_trading",
        "kill_switch_enabled",
    )
    list_filter = ("is_active", "is_default", "allow_live_trading", "kill_switch_enabled")
    search_fields = ("user__email", "portfolio__name", "name")


@admin.register(DailyRiskState)
class DailyRiskStateAdmin(admin.ModelAdmin):
    list_display = (
        "id", "portfolio", "day", "realized_pnl", "unrealized_pnl",
        "total_loss_amount", "total_loss_percent",
        "blocked_new_positions", "kill_switch_triggered",
    )
    list_filter = ("blocked_new_positions", "kill_switch_triggered")
    search_fields = ("portfolio__name",)


@admin.register(WeeklyRiskState)
class WeeklyRiskStateAdmin(admin.ModelAdmin):
    list_display = (
        "id", "portfolio", "week_start", "realized_pnl", "unrealized_pnl",
        "total_loss_amount", "total_loss_percent",
        "blocked_new_positions", "kill_switch_triggered",
    )
    list_filter = ("blocked_new_positions", "kill_switch_triggered")
    search_fields = ("portfolio__name",)


@admin.register(RiskDecision)
class RiskDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "portfolio", "symbol", "decision",
        "requested_stake", "approved_stake",
        "requested_quantity", "approved_quantity",
        "expected_loss", "risk_reward_ratio",
        "created_at",
    )
    list_filter = ("decision", "asset_class")
    search_fields = ("portfolio__name", "symbol", "blocking_reason")


@admin.register(KillSwitchEvent)
class KillSwitchEventAdmin(admin.ModelAdmin):
    list_display = (
        "id", "portfolio", "reason_code", "is_active",
        "triggered_at", "resolved_at",
    )
    list_filter = ("is_active", "reason_code")
    search_fields = ("portfolio__name", "reason_code", "reason")


# ─────────────────────────────────────────────────────────────────────────────
#  RiskOverrideAudit — lecture seule, export CSV
# ─────────────────────────────────────────────────────────────────────────────

def _export_override_audit_csv(modeladmin, request, queryset):
    """
    Action admin : exporte les enregistrements sélectionnés au format CSV.

    Colonnes incluses pour archivage légal :
      id, overridden_at, user_email, portfolio, symbol, side,
      requested_stake, codes_bypassed, reason, ip_address, user_agent,
      profile_snapshot (JSON inline).
    """
    now_str = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"risk_override_audit_{now_str}.csv"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    # BOM UTF-8 pour compatibilité Excel
    response.write("﻿")

    writer = csv.writer(response, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "id",
        "overridden_at",
        "user_email",
        "user_id",
        "portfolio_id",
        "portfolio_name",
        "symbol",
        "side",
        "requested_stake",
        "codes_bypassed",
        "reason",
        "ip_address",
        "user_agent",
        "profile_snapshot",
        "risk_decision_id",
    ])

    for obj in queryset.select_related("user", "portfolio", "risk_decision").iterator():
        writer.writerow([
            obj.id,
            obj.overridden_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            getattr(obj.user, "email", "") if obj.user else "",
            obj.user_id or "",
            obj.portfolio_id or "",
            obj.portfolio.name if obj.portfolio else "",
            obj.symbol,
            obj.side,
            obj.requested_stake,
            json.dumps(obj.codes_bypassed, ensure_ascii=False),
            obj.reason,
            obj.ip_address or "",
            obj.user_agent,
            json.dumps(obj.profile_snapshot, ensure_ascii=False),
            obj.risk_decision_id or "",
        ])

    return response


_export_override_audit_csv.short_description = "Exporter la sélection en CSV (archivage légal)"


@admin.register(RiskOverrideAudit)
class RiskOverrideAuditAdmin(admin.ModelAdmin):
    """
    Vue admin en LECTURE SEULE pour les enregistrements d'audit override.

    Aucun ajout / modification / suppression autorisé depuis l'interface :
    les enregistrements sont créés exclusivement par RiskGuardService
    et ne doivent jamais être altérés manuellement.
    """

    list_display = (
        "id",
        "overridden_at",
        "user",
        "portfolio",
        "symbol",
        "side",
        "requested_stake",
        "codes_bypassed_display",
        "reason_short",
        "ip_address",
        "risk_decision",
    )
    list_filter = ("side", "overridden_at")
    search_fields = (
        "user__email",
        "portfolio__name",
        "symbol",
        "reason",
        "ip_address",
    )
    date_hierarchy = "overridden_at"
    ordering = ("-overridden_at",)
    actions = [_export_override_audit_csv]

    readonly_fields = (
        "id",
        "overridden_at",
        "user",
        "portfolio",
        "risk_decision",
        "symbol",
        "side",
        "requested_stake",
        "codes_bypassed",
        "reason",
        "ip_address",
        "user_agent",
        "profile_snapshot",
    )

    fieldsets = (
        ("Identité", {
            "fields": ("id", "overridden_at", "user", "portfolio", "risk_decision"),
        }),
        ("Trade", {
            "fields": ("symbol", "side", "requested_stake"),
        }),
        ("Décharge", {
            "fields": ("codes_bypassed", "reason"),
        }),
        ("Contexte réseau", {
            "fields": ("ip_address", "user_agent"),
            "classes": ("collapse",),
        }),
        ("Snapshot profil au moment de l'override", {
            "fields": ("profile_snapshot",),
            "classes": ("collapse",),
        }),
    )

    # ── Empêche tout modification depuis l'admin ──────────────────────────

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ── Colonnes calculées ────────────────────────────────────────────────

    @admin.display(description="Codes franchis")
    def codes_bypassed_display(self, obj):
        if not obj.codes_bypassed:
            return "—"
        return ", ".join(obj.codes_bypassed)

    @admin.display(description="Raison (extrait)")
    def reason_short(self, obj):
        if not obj.reason:
            return "—"
        return obj.reason[:60] + ("…" if len(obj.reason) > 60 else "")