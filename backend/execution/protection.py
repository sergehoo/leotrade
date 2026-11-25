from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.outbox import OutboxService
from execution.event_topics import ORDER_SUBMIT_REQUESTED
from execution.models import Order, PositionProtection
from execution.trailing import TrailingStopService
from portfolio.models import Position


log = logging.getLogger("lyneci.execution.protection")

PRICE_QUANT = Decimal("0.00000001")
ACTIVE_CLOSE_STATUSES = (
    "PENDING_SUBMIT",
    "SUBMITTING",
    "UNKNOWN_BROKER_STATE",
    "SUBMITTED",
    "PARTIALLY_FILLED",
)


def _decimal(value, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _price(value) -> Decimal | None:
    parsed = _decimal(value)
    if parsed <= 0:
        return None
    return parsed.quantize(PRICE_QUANT)


class ProtectionCapabilityService:
    @staticmethod
    def resolve(position: Position, *, trailing_enabled: bool) -> tuple[str, str]:
        broker = position.broker_account
        if broker.mode == "PAPER":
            return "LOCAL_MONITORED", "paper_local_monitoring"
        if broker.broker == "MT5" and not trailing_enabled:
            return "NATIVE_BROKER", "mt5_initial_sl_tp"
        if broker.broker == "MT5":
            return "UNSUPPORTED", "mt5_trailing_modification_not_configured"
        if broker.broker == "BINANCE":
            return "UNSUPPORTED", "binance_conditional_order_not_configured"
        if broker.broker == "DERIV":
            return "UNSUPPORTED", "deriv_contract_protection_not_configured"
        return "UNSUPPORTED", "broker_protection_not_supported"


class PositionProtectionService:
    @staticmethod
    @transaction.atomic
    def sync_from_position(position: Position, *, order: Order | None = None):
        position = (
            Position.objects
            .select_for_update()
            .select_related("broker_account")
            .get(pk=position.pk)
        )
        metadata = order.metadata or {} if order is not None else {}
        existing = PositionProtection.objects.filter(position=position).first()
        trailing_keys_present = any(
            key in metadata
            for key in ("trailing_stop_enabled", "trailing_enabled")
        )
        trailing_enabled = (
            bool(
                metadata.get("trailing_stop_enabled")
                or metadata.get("trailing_enabled")
            )
            if trailing_keys_present
            else bool(getattr(existing, "trailing_enabled", False))
        )

        stop_loss = _price(position.stop_loss)
        take_profit = _price(position.take_profit)
        if not stop_loss and not take_profit and not trailing_enabled and existing is None:
            return None
        if existing and existing.status in {"EXECUTING", "COMPLETED"}:
            return existing

        mode, capability_reason = ProtectionCapabilityService.resolve(
            position,
            trailing_enabled=trailing_enabled,
        )
        validation_error = PositionProtectionService._validate_levels(
            position=position,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        status = "ACTIVE" if mode != "UNSUPPORTED" and not validation_error else "DISABLED"
        entry = _price(position.average_entry_price or position.entry_price)

        defaults = {
            "mode": mode,
            "status": status,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_enabled": trailing_enabled,
            "trail_percent": _decimal(
                metadata.get("trail_percent"),
                str(getattr(existing, "trail_percent", Decimal("0.015"))),
            ),
            "atr": _price(metadata.get("atr")) or getattr(existing, "atr", None),
            "atr_multiplier": _decimal(
                metadata.get("atr_multiplier"),
                str(getattr(existing, "atr_multiplier", Decimal("2"))),
            ),
            "break_even_after_r": _decimal(
                metadata.get("break_even_after_r"),
                str(getattr(existing, "break_even_after_r", Decimal("1"))),
            ),
            "high_watermark": getattr(existing, "high_watermark", None) or entry,
            "low_watermark": getattr(existing, "low_watermark", None) or entry,
            "last_error": validation_error,
            "metadata": {
                **(getattr(existing, "metadata", None) or {}),
                "capability_reason": capability_reason,
                "origin_order_id": order.id if order is not None else None,
            },
        }
        protection, _ = PositionProtection.objects.update_or_create(
            position=position,
            defaults=defaults,
        )
        return protection

    @staticmethod
    def _validate_levels(
        *,
        position: Position,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
    ) -> str:
        entry = _price(position.average_entry_price or position.entry_price)
        if entry is None:
            return "invalid_entry_price"
        if position.side == "LONG":
            if stop_loss is not None and stop_loss >= entry:
                return "long_stop_loss_must_be_below_entry"
            if take_profit is not None and take_profit <= entry:
                return "long_take_profit_must_be_above_entry"
        elif position.side == "SHORT":
            if stop_loss is not None and stop_loss <= entry:
                return "short_stop_loss_must_be_above_entry"
            if take_profit is not None and take_profit >= entry:
                return "short_take_profit_must_be_below_entry"
        else:
            return "invalid_position_side"
        return ""

    @staticmethod
    @transaction.atomic
    def evaluate(protection_id: int) -> dict:
        protection = (
            PositionProtection.objects
            .select_for_update()
            .select_related("position__broker_account", "position__portfolio", "position__asset")
            .filter(pk=protection_id)
            .first()
        )
        if protection is None:
            return {"status": "missing"}
        position = Position.objects.select_for_update().get(pk=protection.position_id)

        if position.status not in {"OPEN", "PARTIALLY_CLOSED"}:
            PositionProtectionService._complete_locked(protection)
            return {"status": "completed", "reason": "position_closed"}
        if protection.status != "ACTIVE":
            return {"status": "skipped", "reason": protection.status.lower()}
        if protection.mode != "LOCAL_MONITORED":
            protection.last_evaluated_at = timezone.now()
            protection.save(update_fields=["last_evaluated_at", "updated_at"])
            return {"status": "skipped", "reason": protection.mode.lower()}

        now = timezone.now()
        max_age_seconds = int(
            getattr(settings, "POSITION_PROTECTION_MAX_PRICE_AGE_SECONDS", 45)
        )
        price_age = (now - position.updated_at).total_seconds()
        current_price = _price(position.current_price)
        if current_price is None or price_age > max_age_seconds:
            protection.last_evaluated_at = now
            protection.last_error = "stale_or_missing_market_price"
            protection.save(update_fields=[
                "last_evaluated_at",
                "last_error",
                "updated_at",
            ])
            return {"status": "skipped", "reason": "stale_or_missing_market_price"}

        protection.last_price = current_price
        protection.last_evaluated_at = now
        protection.last_error = ""
        protection.high_watermark = max(
            _price(protection.high_watermark) or current_price,
            current_price,
        )
        protection.low_watermark = min(
            _price(protection.low_watermark) or current_price,
            current_price,
        )

        if protection.trailing_enabled:
            reference_price = (
                protection.high_watermark
                if position.side == "LONG"
                else protection.low_watermark
            )
            adjustment = TrailingStopService.compute(
                entry_price=position.average_entry_price or position.entry_price,
                current_price=reference_price,
                side=position.side,
                stop_loss=protection.stop_loss,
                take_profit=protection.take_profit,
                atr=protection.atr,
                atr_multiplier=protection.atr_multiplier,
                trail_percent=protection.trail_percent,
                break_even_after_r=protection.break_even_after_r,
            )
            adjusted_stop = _price(adjustment.new_stop_loss)
            if PositionProtectionService._is_tighter_stop(
                side=position.side,
                current=protection.stop_loss,
                candidate=adjusted_stop,
            ):
                protection.stop_loss = adjusted_stop
                Position.objects.filter(pk=position.pk).update(
                    stop_loss=adjusted_stop,
                    updated_at=now,
                )

        trigger_reason = PositionProtectionService._trigger_reason(
            side=position.side,
            current_price=current_price,
            stop_loss=protection.stop_loss,
            take_profit=protection.take_profit,
        )
        if not trigger_reason:
            protection.save(update_fields=[
                "stop_loss",
                "high_watermark",
                "low_watermark",
                "last_price",
                "last_evaluated_at",
                "last_error",
                "updated_at",
            ])
            return {
                "status": "active",
                "stop_loss": str(protection.stop_loss) if protection.stop_loss else None,
            }

        existing_close = position.closing_orders.filter(
            status__in=ACTIVE_CLOSE_STATUSES,
        ).first()
        if existing_close is not None:
            protection.status = "EXECUTING"
            protection.close_order = existing_close
            protection.triggered_at = now
            protection.trigger_reason = trigger_reason
            protection.save(update_fields=[
                "status",
                "close_order",
                "triggered_at",
                "trigger_reason",
                "last_price",
                "last_evaluated_at",
                "updated_at",
            ])
            return {"status": "executing", "order_id": existing_close.id}

        order = PositionProtectionService._create_close_order(
            position=position,
            protection=protection,
            current_price=current_price,
            trigger_reason=trigger_reason,
        )
        protection.status = "EXECUTING"
        protection.close_order = order
        protection.triggered_at = now
        protection.trigger_reason = trigger_reason
        protection.save(update_fields=[
            "status",
            "close_order",
            "triggered_at",
            "trigger_reason",
            "high_watermark",
            "low_watermark",
            "last_price",
            "last_evaluated_at",
            "last_error",
            "updated_at",
        ])
        return {
            "status": "triggered",
            "reason": trigger_reason,
            "order_id": order.id,
        }

    @staticmethod
    def _create_close_order(
        *,
        position: Position,
        protection: PositionProtection,
        current_price: Decimal,
        trigger_reason: str,
    ) -> Order:
        from execution.services import ExecutionOrchestrator

        quantity = _decimal(position.quantity).quantize(PRICE_QUANT)
        notional = (quantity * current_price).quantize(Decimal("0.01"))
        order = ExecutionOrchestrator.create_order(
            user=position.portfolio.user,
            portfolio=position.portfolio,
            broker_account=position.broker_account,
            closes_position=position,
            symbol=position.symbol,
            side="SELL" if position.side == "LONG" else "BUY",
            approved_quantity=quantity,
            requested_stake_amount=notional,
            approved_notional=notional,
            requested_price=current_price,
            asset=position.asset,
            source="STRATEGY",
            idempotency_key=f"position-protection:{protection.id}:close",
            metadata={
                "reduce_only": True,
                "closes_position_id": position.id,
                "position_protection_id": protection.id,
                "protection_trigger": trigger_reason,
            },
        )
        OutboxService.enqueue(
            topic=ORDER_SUBMIT_REQUESTED,
            aggregate_type="execution.Order",
            aggregate_id=order.id,
            payload={"order_id": order.id},
            idempotency_key=f"order:{order.id}:submit",
        )
        return order

    @staticmethod
    def _is_tighter_stop(*, side: str, current, candidate) -> bool:
        if candidate is None:
            return False
        current_stop = _price(current)
        if current_stop is None:
            return True
        if side == "LONG":
            return candidate > current_stop
        return candidate < current_stop

    @staticmethod
    def _trigger_reason(*, side: str, current_price, stop_loss, take_profit) -> str:
        stop = _price(stop_loss)
        target = _price(take_profit)
        if side == "LONG":
            if stop is not None and current_price <= stop:
                return "STOP_LOSS"
            if target is not None and current_price >= target:
                return "TAKE_PROFIT"
        else:
            if stop is not None and current_price >= stop:
                return "STOP_LOSS"
            if target is not None and current_price <= target:
                return "TAKE_PROFIT"
        return ""

    @staticmethod
    @transaction.atomic
    def mark_execution_failed(order: Order, error: str) -> None:
        protection = (
            PositionProtection.objects
            .select_for_update()
            .filter(close_order=order)
            .first()
        )
        if protection is None or protection.status == "COMPLETED":
            return
        protection.status = "FAILED"
        protection.last_error = error[:1000]
        protection.save(update_fields=["status", "last_error", "updated_at"])

    @staticmethod
    @transaction.atomic
    def mark_execution_unknown(order: Order, error: str) -> None:
        protection = (
            PositionProtection.objects
            .select_for_update()
            .filter(close_order=order)
            .first()
        )
        if protection is None or protection.status == "COMPLETED":
            return
        protection.last_error = error[:1000]
        protection.save(update_fields=["last_error", "updated_at"])

    @staticmethod
    @transaction.atomic
    def mark_completed(position: Position) -> None:
        protection = (
            PositionProtection.objects
            .select_for_update()
            .filter(position=position)
            .first()
        )
        if protection is not None:
            PositionProtectionService._complete_locked(protection)

    @staticmethod
    def _complete_locked(protection: PositionProtection) -> None:
        protection.status = "COMPLETED"
        protection.completed_at = timezone.now()
        protection.last_error = ""
        protection.save(update_fields=[
            "status",
            "completed_at",
            "last_error",
            "updated_at",
        ])

    @staticmethod
    def evaluate_active(*, limit: int = 500) -> dict:
        protection_ids = list(
            PositionProtection.objects
            .filter(status="ACTIVE")
            .order_by("last_evaluated_at", "id")
            .values_list("id", flat=True)[:limit]
        )
        counts = {"active": 0, "triggered": 0, "skipped": 0, "completed": 0, "errors": 0}
        for protection_id in protection_ids:
            try:
                result = PositionProtectionService.evaluate(protection_id)
            except Exception as exc:
                counts["errors"] += 1
                log.exception(
                    "position_protection.evaluate_failed protection_id=%s err=%s",
                    protection_id,
                    exc,
                )
                continue
            status = result.get("status", "skipped")
            if status in counts:
                counts[status] += 1
            elif status == "executing":
                counts["triggered"] += 1
            else:
                counts["skipped"] += 1
        counts["processed"] = len(protection_ids)
        return counts
