from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError

from execution.models import Order as ExecutionOrder
from execution.services import ExecutionOrchestrator
from strategies.models import Signal
from trading.models import TradingIntent, TradingIntentEvent


class CanonicalSignalExecutionService:
    """Compatibility entry point backed exclusively by the canonical OMS."""

    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    @staticmethod
    def _decimal(value, default: str = "0") -> Decimal:
        try:
            if value is None:
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    def _validate_scope(self, signal: Signal) -> None:
        user = self.broker_account.user
        if self.portfolio.user_id != user.id:
            raise ValueError("Le portefeuille n'appartient pas au propriétaire du broker.")
        if self.portfolio.broker_account_id != self.broker_account.id:
            raise ValueError("Le broker ne correspond pas au portefeuille.")
        if not Signal.objects.executable_by(user).filter(pk=signal.pk).exists():
            raise ValueError("Le signal n'est pas exécutable par cet utilisateur.")
        if signal.status not in {"APPROVED", "QUEUED"}:
            raise ValueError("Le signal doit être approuvé avant exécution.")

    def _sizing(self, signal: Signal, approved_quantity: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        price = self._decimal(signal.price)
        if self.broker_account.broker == "DERIV":
            return Decimal("1"), approved_quantity, approved_quantity

        notional = (abs(approved_quantity) * price).quantize(Decimal("0.01"))
        if price <= 0 or notional <= 0:
            raise ValueError("Un prix de référence positif est requis pour calculer le notionnel.")
        return approved_quantity, notional, notional

    @staticmethod
    def _metadata(signal: Signal, intent: TradingIntent | None) -> dict:
        parameters = signal.strategy.parameters or {}
        try:
            duration = max(1, int(parameters.get("deriv_duration", 5)))
        except (TypeError, ValueError):
            duration = 5
        duration_unit = str(parameters.get("deriv_duration_unit", "m")).lower()
        if duration_unit not in {"s", "m", "h", "d", "t"}:
            duration_unit = "m"
        metadata = {
            "compatibility_entrypoint": "trading.ExecutionService",
            "duration": duration,
            "duration_unit": duration_unit,
        }
        if parameters.get("deriv_multiplier") is not None:
            try:
                metadata["multiplier"] = max(1, int(parameters["deriv_multiplier"]))
            except (TypeError, ValueError):
                pass
        if intent is not None:
            metadata["trading_intent_id"] = intent.id
        return metadata

    def execute(
        self,
        *,
        signal: Signal,
        approved_quantity: Decimal,
        intent: TradingIntent | None = None,
    ) -> ExecutionOrder:
        approved_quantity = self._decimal(approved_quantity)
        if signal.side == "HOLD" or approved_quantity <= 0:
            raise ValueError("Signal non exécutable.")

        self._validate_scope(signal)
        quantity, stake, notional = self._sizing(signal, approved_quantity)
        idempotency_key = (
            f"signal:{signal.id}:portfolio:{self.portfolio.id}:"
            f"broker:{self.broker_account.id}"
        )
        existing = ExecutionOrder.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

        try:
            order = ExecutionOrchestrator.create_order(
                user=self.broker_account.user,
                portfolio=self.portfolio,
                broker_account=self.broker_account,
                symbol=signal.strategy.asset.symbol,
                side=signal.side,
                approved_quantity=quantity,
                requested_stake_amount=stake,
                approved_notional=notional,
                requested_price=self._decimal(signal.price),
                signal=signal,
                asset=signal.strategy.asset,
                source="STRATEGY",
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                idempotency_key=idempotency_key,
                metadata=self._metadata(signal, intent),
            )
        except IntegrityError:
            existing = ExecutionOrder.objects.filter(idempotency_key=idempotency_key).first()
            if existing is None:
                raise
            return existing

        if intent is not None:
            TradingIntentEvent.objects.create(
                intent=intent,
                event_type="ORDER_CREATED",
                title="Ordre créé",
                message=f"{order.symbol} {order.side} via le moteur d'exécution central.",
                payload={"execution_order_id": order.id},
            )

        return ExecutionOrchestrator.submit_order(order)
