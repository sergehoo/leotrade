# from __future__ import annotations
#
# from django.contrib import admin
# from django.db.models import Count
# from django.utils import timezone
# from django.utils.html import format_html
#
# from .models import (
#     TradingIntent,
#     TradingIntentEvent,
#     Order,
#     TradeExecution,
#     DerivContract,
#     TradeIdea,
#     TradeIdeaFeedback,
#     AgentRun,
#     MarketRegimeSnapshot,
#     TradeIdeaReview,
#     PortfolioAdvice,
# )
#
#
# # =========================================================
# # Helpers
# # =========================================================
#
# class ReadOnlyTimeStampedAdmin(admin.ModelAdmin):
#     readonly_fields = ("created_at", "updated_at")
#     ordering = ("-created_at",)
#
#
# def colored_badge(label: str, bg: str = "#334155", fg: str = "#ffffff"):
#     return format_html(
#         '<span style="padding:4px 10px;border-radius:999px;'
#         'background:{};color:{};font-weight:600;font-size:11px;">{}</span>',
#         bg,
#         fg,
#         label,
#     )
#
#
# # =========================================================
# # TradingIntentEvent Inline
# # =========================================================
#
# class TradingIntentEventInline(admin.TabularInline):
#     model = TradingIntentEvent
#     extra = 0
#     can_delete = False
#     fields = ("created_at", "event_type", "title", "message")
#     readonly_fields = ("created_at", "event_type", "title", "message")
#     show_change_link = True
#     ordering = ("-created_at",)
#
#
# # =========================================================
# # Trading Intent
# # =========================================================
#
# @admin.register(TradingIntent)
# class TradingIntentAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "title",
#         "user",
#         "portfolio",
#         "broker_account",
#         "execution_mode_badge",
#         "status_badge",
#         "risk_level_badge",
#         "capital_amount",
#         "allocated_amount",
#         "actual_return_percent",
#         "started_at",
#         "expires_at",
#     )
#     list_filter = (
#         "status",
#         "risk_level",
#         "execution_mode",
#         "approved_by_user",
#         "created_at",
#         "started_at",
#         "ended_at",
#         "broker_account",
#     )
#     search_fields = (
#         "title",
#         "objective_prompt",
#         "user__username",
#         "user__email",
#         "portfolio__name",
#         "broker_account__name",
#     )
#     autocomplete_fields = ("user", "broker_account", "portfolio", "strategy")
#     readonly_fields = (
#         "created_at",
#         "updated_at",
#         "is_live_display",
#         "is_running_display",
#     )
#     inlines = [TradingIntentEventInline]
#     list_select_related = ("user", "broker_account", "portfolio", "strategy")
#     date_hierarchy = "created_at"
#
#     fieldsets = (
#         ("Identification", {
#             "fields": (
#                 "user",
#                 "portfolio",
#                 "broker_account",
#                 "strategy",
#                 "title",
#                 "objective_prompt",
#             )
#         }),
#         ("Capital & objectifs", {
#             "fields": (
#                 "capital_amount",
#                 "allocated_amount",
#                 "capital_currency",
#                 "target_return_percent",
#                 "max_loss_percent",
#                 "duration_days",
#                 "max_open_positions",
#             )
#         }),
#         ("Risque & exécution", {
#             "fields": (
#                 "risk_level",
#                 "execution_mode",
#                 "allowed_asset_classes",
#                 "approved_by_user",
#             )
#         }),
#         ("IA", {
#             "classes": ("collapse",),
#             "fields": (
#                 "ai_feasibility_score",
#                 "ai_analysis",
#                 "ai_plan",
#             )
#         }),
#         ("Performance & état", {
#             "fields": (
#                 "status",
#                 "rejection_reason",
#                 "realized_pnl",
#                 "unrealized_pnl",
#                 "actual_return_percent",
#                 "started_at",
#                 "ended_at",
#                 "expires_at",
#                 "is_live_display",
#                 "is_running_display",
#             )
#         }),
#         ("Audit", {
#             "classes": ("collapse",),
#             "fields": ("created_at", "updated_at"),
#         }),
#     )
#
#     @admin.display(description="Mode")
#     def execution_mode_badge(self, obj):
#         if obj.execution_mode == "LIVE":
#             return colored_badge("LIVE", "#7c2d12", "#fdba74")
#         return colored_badge("PAPER", "#1e3a8a", "#93c5fd")
#
#     @admin.display(description="Statut")
#     def status_badge(self, obj):
#         colors = {
#             "DRAFT": ("#334155", "#e2e8f0"),
#             "ANALYZING": ("#312e81", "#c7d2fe"),
#             "PLANNED": ("#1e40af", "#bfdbfe"),
#             "APPROVED": ("#166534", "#bbf7d0"),
#             "RUNNING": ("#065f46", "#a7f3d0"),
#             "COMPLETED": ("#14532d", "#dcfce7"),
#             "STOPPED": ("#78350f", "#fde68a"),
#             "REJECTED": ("#7f1d1d", "#fecaca"),
#             "FAILED": ("#991b1b", "#fee2e2"),
#             "EXPIRED": ("#44403c", "#e7e5e4"),
#         }
#         bg, fg = colors.get(obj.status, ("#334155", "#fff"))
#         return colored_badge(obj.status, bg, fg)
#
#     @admin.display(description="Risque")
#     def risk_level_badge(self, obj):
#         colors = {
#             "LOW": ("#14532d", "#dcfce7"),
#             "MEDIUM": ("#1e3a8a", "#bfdbfe"),
#             "HIGH": ("#78350f", "#fde68a"),
#             "AGGRESSIVE": ("#7f1d1d", "#fecaca"),
#         }
#         bg, fg = colors.get(obj.risk_level, ("#334155", "#fff"))
#         return colored_badge(obj.risk_level, bg, fg)
#
#     @admin.display(description="Is live")
#     def is_live_display(self, obj):
#         return obj.is_live
#
#     @admin.display(description="Is running")
#     def is_running_display(self, obj):
#         return obj.is_running
#
#
# # =========================================================
# # Trading Intent Event
# # =========================================================
#
# @admin.register(TradingIntentEvent)
# class TradingIntentEventAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "intent",
#         "event_type",
#         "title",
#         "created_at",
#     )
#     list_filter = ("event_type", "created_at")
#     search_fields = (
#         "intent__title",
#         "title",
#         "message",
#     )
#     autocomplete_fields = ("intent",)
#     readonly_fields = ("created_at", "updated_at")
#
#
# # =========================================================
# # Order
# # =========================================================
#
# @admin.register(Order)
# class OrderAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "symbol",
#         "side_badge",
#         "order_type",
#         "status_badge",
#         "portfolio",
#         "broker_account",
#         "quantity",
#         "filled_quantity",
#         "price",
#         "average_fill_price",
#         "placed_at",
#         "filled_at",
#     )
#     list_filter = (
#         "side",
#         "order_type",
#         "status",
#         "time_in_force",
#         "broker_account",
#         "portfolio",
#         "created_at",
#         "placed_at",
#         "filled_at",
#     )
#     search_fields = (
#         "symbol",
#         "client_order_id",
#         "external_order_id",
#         "notes",
#         "error_message",
#         "portfolio__name",
#     )
#     autocomplete_fields = (
#         "broker_account",
#         "portfolio",
#         "intent",
#         "signal",
#         "position",
#     )
#     list_select_related = (
#         "broker_account",
#         "portfolio",
#         "intent",
#         "signal",
#         "position",
#     )
#     readonly_fields = ("created_at", "updated_at")
#     date_hierarchy = "created_at"
#
#     fieldsets = (
#         ("Relations", {
#             "fields": ("broker_account", "portfolio", "intent", "signal", "position")
#         }),
#         ("Exécution", {
#             "fields": (
#                 "symbol",
#                 "side",
#                 "order_type",
#                 "time_in_force",
#                 "status",
#             )
#         }),
#         ("Quantités & prix", {
#             "fields": (
#                 "quantity",
#                 "filled_quantity",
#                 "price",
#                 "average_fill_price",
#                 "stop_loss",
#                 "take_profit",
#             )
#         }),
#         ("Références", {
#             "fields": (
#                 "client_order_id",
#                 "external_order_id",
#             )
#         }),
#         ("Dates", {
#             "fields": (
#                 "placed_at",
#                 "filled_at",
#                 "cancelled_at",
#             )
#         }),
#         ("Diagnostic", {
#             "classes": ("collapse",),
#             "fields": (
#                 "broker_payload",
#                 "error_message",
#                 "notes",
#             )
#         }),
#         ("Audit", {
#             "classes": ("collapse",),
#             "fields": ("created_at", "updated_at"),
#         }),
#     )
#
#     @admin.display(description="Side")
#     def side_badge(self, obj):
#         if obj.side == "BUY":
#             return colored_badge("BUY", "#14532d", "#dcfce7")
#         return colored_badge("SELL", "#7f1d1d", "#fecaca")
#
#     @admin.display(description="Statut")
#     def status_badge(self, obj):
#         colors = {
#             "PENDING": ("#334155", "#e2e8f0"),
#             "PLACED": ("#1e3a8a", "#bfdbfe"),
#             "FILLED": ("#166534", "#bbf7d0"),
#             "PARTIALLY_FILLED": ("#78350f", "#fde68a"),
#             "CANCELLED": ("#44403c", "#e7e5e4"),
#             "REJECTED": ("#7f1d1d", "#fecaca"),
#             "FAILED": ("#991b1b", "#fee2e2"),
#         }
#         bg, fg = colors.get(obj.status, ("#334155", "#fff"))
#         return colored_badge(obj.status, bg, fg)
#
#
# # =========================================================
# # Trade Execution
# # =========================================================
#
# @admin.register(TradeExecution)
# class TradeExecutionAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "order",
#         "execution_id",
#         "execution_price",
#         "execution_qty",
#         "fee",
#         "fee_asset",
#         "liquidity",
#         "executed_at",
#     )
#     list_filter = ("liquidity", "executed_at", "created_at")
#     search_fields = (
#         "execution_id",
#         "order__symbol",
#         "order__client_order_id",
#         "order__external_order_id",
#     )
#     autocomplete_fields = ("order",)
#     list_select_related = ("order",)
#     readonly_fields = ("created_at", "updated_at")
#
#
# # =========================================================
# # Deriv Contract
# # =========================================================
#
# @admin.register(DerivContract)
# class DerivContractAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "contract_id",
#         "symbol",
#         "contract_type",
#         "status_badge",
#         "portfolio",
#         "broker_account",
#         "buy_price",
#         "payout",
#         "profit",
#         "purchased_at",
#         "expires_at",
#     )
#     list_filter = (
#         "status",
#         "is_expired",
#         "is_sold",
#         "contract_type",
#         "currency",
#         "broker_account",
#         "portfolio",
#         "created_at",
#     )
#     search_fields = (
#         "contract_id",
#         "transaction_id",
#         "symbol",
#         "error_message",
#     )
#     autocomplete_fields = ("order", "broker_account", "portfolio", "signal")
#     list_select_related = ("order", "broker_account", "portfolio", "signal")
#     readonly_fields = ("created_at", "updated_at")
#
#     fieldsets = (
#         ("Relations", {
#             "fields": ("order", "broker_account", "portfolio", "signal")
#         }),
#         ("Contrat", {
#             "fields": (
#                 "contract_id",
#                 "transaction_id",
#                 "symbol",
#                 "contract_type",
#                 "status",
#                 "currency",
#             )
#         }),
#         ("Conditions", {
#             "fields": (
#                 "duration",
#                 "duration_unit",
#                 "buy_price",
#                 "payout",
#                 "profit",
#                 "entry_tick",
#                 "exit_tick",
#             )
#         }),
#         ("Cycle de vie", {
#             "fields": (
#                 "is_expired",
#                 "is_sold",
#                 "purchased_at",
#                 "expires_at",
#                 "settled_at",
#             )
#         }),
#         ("Payloads", {
#             "classes": ("collapse",),
#             "fields": (
#                 "proposal_payload",
#                 "buy_payload",
#                 "latest_contract_payload",
#                 "error_message",
#             )
#         }),
#         ("Audit", {
#             "classes": ("collapse",),
#             "fields": ("created_at", "updated_at"),
#         }),
#     )
#
#     @admin.display(description="Statut")
#     def status_badge(self, obj):
#         colors = {
#             "OPEN": ("#1e3a8a", "#bfdbfe"),
#             "WON": ("#166534", "#bbf7d0"),
#             "LOST": ("#7f1d1d", "#fecaca"),
#             "SOLD": ("#78350f", "#fde68a"),
#             "CANCELLED": ("#44403c", "#e7e5e4"),
#             "EXPIRED": ("#57534e", "#e7e5e4"),
#             "FAILED": ("#991b1b", "#fee2e2"),
#         }
#         bg, fg = colors.get(obj.status, ("#334155", "#fff"))
#         return colored_badge(obj.status, bg, fg)
#
#
# # =========================================================
# # Trade Idea Feedback Inline
# # =========================================================
#
# class TradeIdeaFeedbackInline(admin.StackedInline):
#     model = TradeIdeaFeedback
#     extra = 0
#     can_delete = False
#     autocomplete_fields = ("signal",)
#
#
# # =========================================================
# # Trade Idea
# # =========================================================
#
# @admin.action(description="Marquer comme REVIEW")
# def mark_tradeideas_review(modeladmin, request, queryset):
#     queryset.update(status="REVIEW")
#
#
# @admin.action(description="Marquer comme APPROVED")
# def mark_tradeideas_approved(modeladmin, request, queryset):
#     queryset.update(status="APPROVED")
#
#
# @admin.action(description="Marquer comme REJECTED")
# def mark_tradeideas_rejected(modeladmin, request, queryset):
#     queryset.update(status="REJECTED")
#
#
# @admin.action(description="Marquer comme EXPIRED")
# def mark_tradeideas_expired(modeladmin, request, queryset):
#     queryset.update(status="EXPIRED")
#
#
# # @admin.register(TradeIdea)
# # class TradeIdeaAdmin(ReadOnlyTimeStampedAdmin):
# #     list_display = (
# #         "id",
# #         "symbol",
# #         "direction_badge",
# #         "status_badge",
# #         "user",
# #         "timeframe",
# #         "strategy",
# #         "signal",
# #         "overall_score",
# #         "confidence_score",
# #         "expected_rr",
# #         "expires_in_display",
# #         "created_at",
# #     )
# #     list_filter = (
# #         "status",
# #         "direction",
# #         "source_type",
# #         "timeframe",
# #         "auto_trade_enabled",
# #         "created_at",
# #         "expires_at",
# #     )
# #     search_fields = (
# #         "symbol",
# #         "explanation",
# #         "user__username",
# #         "user__email",
# #         "asset__symbol",
# #     )
# #     autocomplete_fields = (
# #         "user",
# #         "scan_run",
# #         "asset",
# #         "timeframe",
# #         "strategy",
# #         "signal",
# #     )
# #     list_select_related = (
# #         "user",
# #         "scan_run",
# #         "asset",
# #         "timeframe",
# #         "strategy",
# #         "signal",
# #     )
# #     readonly_fields = (
# #         "created_at",
# #         "updated_at",
# #         "is_expired_display",
# #     )
# #     inlines = [TradeIdeaFeedbackInline]
# #     actions = [
# #         mark_tradeideas_review,
# #         mark_tradeideas_approved,
# #         mark_tradeideas_rejected,
# #         mark_tradeideas_expired,
# #     ]
# #     date_hierarchy = "created_at"
# #
# #     fieldsets = (
# #         ("Relations", {
# #             "fields": (
# #                 "user",
# #                 "scan_run",
# #                 "asset",
# #                 "timeframe",
# #                 "strategy",
# #                 "signal",
# #             )
# #         }),
# #         ("Trade setup", {
# #             "fields": (
# #                 "source_type",
# #                 "symbol",
# #                 "direction",
# #                 "entry_price",
# #                 "stop_loss",
# #                 "take_profit",
# #                 "horizon_minutes",
# #                 "expected_rr",
# #             )
# #         }),
# #         ("Scores", {
# #             "fields": (
# #                 "confidence_score",
# #                 "setup_score",
# #                 "risk_score",
# #                 "reward_score",
# #                 "overall_score",
# #             )
# #         }),
# #         ("Métadonnées", {
# #             "fields": (
# #                 "status",
# #                 "auto_trade_enabled",
# #                 "expires_at",
# #                 "is_expired_display",
# #                 "explanation",
# #             )
# #         }),
# #         ("Payloads", {
# #             "classes": ("collapse",),
# #             "fields": (
# #                 "market_snapshot",
# #                 "features_snapshot",
# #                 "ai_payload",
# #             )
# #         }),
# #         ("Audit", {
# #             "classes": ("collapse",),
# #             "fields": ("created_at", "updated_at"),
# #         }),
# #     )
# #
# #     @admin.display(description="Direction")
# #     def direction_badge(self, obj):
# #         if obj.direction in ("BUY", "CALL"):
# #             return colored_badge(obj.direction, "#14532d", "#dcfce7")
# #         return colored_badge(obj.direction, "#7f1d1d", "#fecaca")
# #
# #     @admin.display(description="Statut")
# #     def status_badge(self, obj):
# #         colors = {
# #             "NEW": ("#1e3a8a", "#bfdbfe"),
# #             "REVIEW": ("#78350f", "#fde68a"),
# #             "APPROVED": ("#166534", "#bbf7d0"),
# #             "REJECTED": ("#7f1d1d", "#fecaca"),
# #             "EXECUTED": ("#065f46", "#a7f3d0"),
# #             "EXPIRED": ("#44403c", "#e7e5e4"),
# #             "CANCELLED": ("#57534e", "#e7e5e4"),
# #         }
# #         bg, fg = colors.get(obj.status, ("#334155", "#fff"))
# #         return colored_badge(obj.status, bg, fg)
# #
# #     @admin.display(description="Expiré ?")
# #     def is_expired_display(self, obj):
# #         return obj.is_expired
# #
# #     @admin.display(description="Expire dans")
# #     def expires_in_display(self, obj):
# #         if not obj.expires_at:
# #             return "—"
# #         delta = obj.expires_at - timezone.now()
# #         seconds = int(delta.total_seconds())
# #         if seconds <= 0:
# #             return format_html('<span style="color:#f87171;font-weight:600;">Expirée</span>')
# #         minutes = seconds // 60
# #         return f"{minutes} min"
#
#
# # =========================================================
# # Trade Idea Feedback
# # =========================================================
#
# @admin.register(TradeIdeaFeedback)
# class TradeIdeaFeedbackAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "idea",
#         "signal",
#         "outcome_badge",
#         "execution_status",
#         "pnl_amount",
#         "pnl_percent",
#         "hit_take_profit",
#         "hit_stop_loss",
#         "evaluated_at",
#     )
#     list_filter = (
#         "outcome",
#         "hit_take_profit",
#         "hit_stop_loss",
#         "created_at",
#         "evaluated_at",
#     )
#     search_fields = (
#         "order_id",
#         "execution_status",
#         "notes",
#         "idea__symbol",
#     )
#     autocomplete_fields = ("idea", "signal")
#     list_select_related = ("idea", "signal")
#     readonly_fields = ("created_at", "updated_at")
#
#     @admin.display(description="Outcome")
#     def outcome_badge(self, obj):
#         colors = {
#             "WIN": ("#166534", "#bbf7d0"),
#             "LOSS": ("#7f1d1d", "#fecaca"),
#             "BREAKEVEN": ("#78350f", "#fde68a"),
#             "OPEN": ("#1e3a8a", "#bfdbfe"),
#             "MISSED": ("#44403c", "#e7e5e4"),
#         }
#         bg, fg = colors.get(obj.outcome, ("#334155", "#fff"))
#         return colored_badge(obj.outcome, bg, fg)
#
#
# # =========================================================
# # Agent Run
# # =========================================================
#
# # @admin.register(AgentRun)
# # class AgentRunAdmin(ReadOnlyTimeStampedAdmin):
# #     list_display = (
# #         "id",
# #         "agent_type",
# #         "status_badge",
# #         "user",
# #         "market_scan_run",
# #         "started_at",
# #         "finished_at",
# #         "runtime_ms",
# #     )
# #     list_filter = ("agent_type", "status", "created_at", "started_at", "finished_at")
# #     search_fields = ("notes", "error_message", "user__username", "user__email")
# #     autocomplete_fields = ("market_scan_run", "user")
# #     list_select_related = ("market_scan_run", "user")
# #     readonly_fields = ("created_at", "updated_at")
# #
# #     @admin.display(description="Statut")
# #     def status_badge(self, obj):
# #         colors = {
# #             "RUNNING": ("#1e3a8a", "#bfdbfe"),
# #             "SUCCEEDED": ("#166534", "#bbf7d0"),
# #             "FAILED": ("#7f1d1d", "#fecaca"),
# #         }
# #         bg, fg = colors.get(obj.status, ("#334155", "#fff"))
# #         return colored_badge(obj.status, bg, fg)
#
#
# # =========================================================
# # Market Regime Snapshot
# # =========================================================
#
# # @admin.register(MarketRegimeSnapshot)
# # class MarketRegimeSnapshotAdmin(ReadOnlyTimeStampedAdmin):
# #     list_display = (
# #         "id",
# #         "market_scan_run",
# #         "timeframe",
# #         "regime_badge",
# #         "confidence",
# #         "risk_posture",
# #         "created_at",
# #     )
# #     list_filter = ("regime", "risk_posture", "timeframe", "created_at")
# #     search_fields = ("summary",)
# #     autocomplete_fields = ("market_scan_run", "timeframe")
# #     list_select_related = ("market_scan_run", "timeframe")
# #     readonly_fields = ("created_at", "updated_at")
# #
# #     @admin.display(description="Regime")
# #     def regime_badge(self, obj):
# #         colors = {
# #             "TREND_BULLISH": ("#14532d", "#dcfce7"),
# #             "TREND_BEARISH": ("#7f1d1d", "#fecaca"),
# #             "RANGE": ("#1e3a8a", "#bfdbfe"),
# #             "VOLATILE": ("#78350f", "#fde68a"),
# #             "MIXED": ("#44403c", "#e7e5e4"),
# #         }
# #         bg, fg = colors.get(obj.regime, ("#334155", "#fff"))
# #         return colored_badge(obj.regime, bg, fg)
#
#
# # =========================================================
# # Trade Idea Review
# # =========================================================
#
# @admin.register(TradeIdeaReview)
# class TradeIdeaReviewAdmin(ReadOnlyTimeStampedAdmin):
#     list_display = (
#         "id",
#         "idea",
#         "decision_badge",
#         "priority",
#         "adjusted_score",
#         "portfolio_fit_score",
#         "market_alignment_score",
#         "agent_run",
#         "created_at",
#     )
#     list_filter = ("decision", "priority", "created_at")
#     search_fields = ("reasoning", "idea__symbol")
#     autocomplete_fields = ("idea", "agent_run")
#     list_select_related = ("idea", "agent_run")
#     readonly_fields = ("created_at", "updated_at")
#
#     @admin.display(description="Decision")
#     def decision_badge(self, obj):
#         colors = {
#             "APPROVE": ("#166534", "#bbf7d0"),
#             "REJECT": ("#7f1d1d", "#fecaca"),
#             "REVIEW": ("#78350f", "#fde68a"),
#         }
#         bg, fg = colors.get(obj.decision, ("#334155", "#fff"))
#         return colored_badge(obj.decision, bg, fg)
#
#
# # =========================================================
# # Portfolio Advice
# # =========================================================
#
# # @admin.register(PortfolioAdvice)
# # class PortfolioAdviceAdmin(ReadOnlyTimeStampedAdmin):
# #     list_display = (
# #         "id",
# #         "portfolio",
# #         "action_badge",
# #         "confidence",
# #         "max_new_positions",
# #         "recommended_risk_percent",
# #         "agent_run",
# #         "created_at",
# #     )
# #     list_filter = ("action", "created_at")
# #     search_fields = ("summary", "portfolio__name")
# #     autocomplete_fields = ("portfolio", "agent_run")
# #     list_select_related = ("portfolio", "agent_run")
# #     readonly_fields = ("created_at", "updated_at")
# #
# #     @admin.display(description="Action")
# #     def action_badge(self, obj):
# #         colors = {
# #             "ALLOW_NEW_POSITIONS": ("#166534", "#bbf7d0"),
# #             "REDUCE_RISK": ("#78350f", "#fde68a"),
# #             "BLOCK_NEW_POSITIONS": ("#7f1d1d", "#fecaca"),
# #             "CLOSE_WEAK_POSITIONS": ("#1e3a8a", "#bfdbfe"),
# #         }
# #         bg, fg = colors.get(obj.action, ("#334155", "#fff"))
# #         return colored_badge(obj.action, bg, fg)