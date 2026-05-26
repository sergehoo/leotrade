from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from brokers.services.binance import BinanceClient
from brokers.services.mt5 import MT5Client
from market.models import Asset, Timeframe
from portfolio.models import Position
from strategies.models import Strategy, Signal
from trading.models import (
    TradingIntent,
    Order,
    TradeExecution,
    TradingIntentEvent,
)
from trading.services.execution.deriv_executor import DerivExecutor


class ExecutionService:
    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    @transaction.atomic
    def execute_signal(
        self,
        signal: Signal,
        approved_quantity: Decimal,
        intent: TradingIntent | None = None,
    ):
        if signal.side == "HOLD" or approved_quantity <= 0:
            raise ValueError("Signal non exécutable.")

        side = "BUY" if signal.side == "BUY" else "SELL"

        order = Order.objects.create(
            broker_account=self.broker_account,
            portfolio=self.portfolio,
            intent=intent,
            signal=signal,
            symbol=signal.strategy.asset.symbol,
            side=side,
            order_type="MARKET",
            quantity=approved_quantity,
            price=signal.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            placed_at=timezone.now(),
            status="PENDING",
        )

        # -------------------------------------------------
        # PAPER MODE
        # -------------------------------------------------
        if self.broker_account.mode == "PAPER":
            order.status = "FILLED"
            order.filled_quantity = approved_quantity
            order.average_fill_price = signal.price
            order.filled_at = timezone.now()
            order.save(update_fields=[
                "status",
                "filled_quantity",
                "average_fill_price",
                "filled_at",
                "updated_at",
            ])

            position = Position.objects.create(
                portfolio=self.portfolio,
                asset=signal.strategy.asset,
                side="LONG" if side == "BUY" else "SHORT",
                quantity=approved_quantity,
                entry_price=signal.price,
                current_price=signal.price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                status="OPEN",
                opened_at=timezone.now(),
            )

            order.position = position
            order.save(update_fields=["position", "updated_at"])

            TradeExecution.objects.create(
                order=order,
                execution_price=signal.price,
                execution_qty=approved_quantity,
                fee=Decimal("0"),
                executed_at=timezone.now(),
                broker_payload={"mode": "PAPER"},
            )

            signal.status = "EXECUTED"
            signal.executed_at = timezone.now()
            signal.save(update_fields=["status", "executed_at", "updated_at"])

            if intent:
                TradingIntentEvent.objects.create(
                    intent=intent,
                    event_type="POSITION_OPENED",
                    title="Position paper ouverte",
                    message=f"{position.asset.symbol} {position.side} {position.quantity}",
                    payload={"order_id": order.id, "position_id": position.id},
                )

            return order

        # -------------------------------------------------
        # BINANCE
        # -------------------------------------------------
        if self.broker_account.broker == "BINANCE":
            client = BinanceClient(
                self.broker_account.api_key,
                self.broker_account.api_secret,
            )
            response = client.create_market_order(
                order.symbol,
                side,
                float(approved_quantity),
            )

            order.external_order_id = str(response.get("orderId"))
            order.client_order_id = str(response.get("clientOrderId", ""))
            order.broker_payload = response
            order.status = "PLACED"
            order.save(update_fields=[
                "external_order_id",
                "client_order_id",
                "broker_payload",
                "status",
                "updated_at",
            ])

            signal.status = "QUEUED"
            signal.save(update_fields=["status", "updated_at"])
            return order

        # -------------------------------------------------
        # DERIV
        # -------------------------------------------------
        if self.broker_account.broker == "DERIV":
            executor = DerivExecutor(self.broker_account, self.portfolio)
            result = executor.execute_signal(signal, approved_quantity)
            return result["order"]

        # -------------------------------------------------
        # MT5
        # -------------------------------------------------
        if self.broker_account.broker == "MT5":
            try:
                import MetaTrader5 as mt5
            except ImportError:
                order.status = "FAILED"
                order.error_message = "Le module MetaTrader5 n'est pas installé sur cet environnement."
                order.save(update_fields=["status", "error_message", "updated_at"])
                raise RuntimeError("MetaTrader5 n'est pas disponible sur cette machine.")

            client = MT5Client(
                login=int(self.broker_account.login),
                password=self.broker_account.password,
                server=self.broker_account.server,
                terminal_path=self.broker_account.terminal_path,
            )
            client.connect()
            try:
                order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
                tick = mt5.symbol_info_tick(order.symbol)

                if tick is None:
                    raise RuntimeError(f"Aucun tick MT5 disponible pour {order.symbol}.")

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": order.symbol,
                    "volume": float(approved_quantity),
                    "type": order_type,
                    "price": tick.ask if side == "BUY" else tick.bid,
                    "deviation": 20,
                    "magic": 20260320,
                    "comment": "hedgeai",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                response = mt5.order_send(request)
            finally:
                client.shutdown()

            order.external_order_id = str(getattr(response, "order", None))
            order.broker_payload = response._asdict() if response else {}
            order.status = "PLACED"
            order.save(update_fields=[
                "external_order_id",
                "broker_payload",
                "status",
                "updated_at",
            ])

            signal.status = "QUEUED"
            signal.save(update_fields=["status", "updated_at"])
            return order

        order.status = "FAILED"
        order.error_message = f"Broker non supporté: {self.broker_account.broker}"
        order.save(update_fields=["status", "error_message", "updated_at"])
        raise ValueError(f"Broker non supporté: {self.broker_account.broker}")


class AIPlanningService:
    @staticmethod
    def build_plan(intent: TradingIntent):
        requested = intent.target_return_percent
        duration = intent.duration_days

        feasibility = "HIGH"
        score = 0.85
        recommended_target = requested

        if requested >= 200 and duration <= 4:
            feasibility = "VERY_LOW"
            score = 0.10
            recommended_target = 10 if intent.risk_level in ["LOW", "MEDIUM"] else 25

        asset_universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        if intent.allowed_asset_classes:
            if "CRYPTO" not in intent.allowed_asset_classes:
                asset_universe = ["EURUSD", "XAUUSD"]

        plan = {
            "strategy_type": "HYBRID",
            "asset_universe": asset_universe,
            "timeframe": "15m" if intent.risk_level in ["HIGH", "AGGRESSIVE"] else "1h",
            "risk_per_trade_percent": (
                1.0 if intent.risk_level == "LOW"
                else 2.0 if intent.risk_level in ["MEDIUM", "HIGH"]
                else 3.0
            ),
            "max_open_positions": intent.max_open_positions or 3,
            "min_confidence_threshold": 0.70 if intent.risk_level == "LOW" else 0.75,
            "execution_mode": intent.execution_mode,
            "recommended_target_return_percent": recommended_target,
        }

        analysis = {
            "requested_return_percent": requested,
            "horizon_days": duration,
            "feasibility": feasibility,
            "feasibility_score": score,
            "recommended_mode": "PAPER" if feasibility == "VERY_LOW" else intent.execution_mode,
            "notes": [
                "L’objectif demandé est analysé automatiquement.",
                "La stratégie est ajustée au niveau de risque déclaré.",
            ],
        }

        return analysis, plan


class IntentExecutionService:
    @staticmethod
    def _resolve_asset_for_intent(intent: TradingIntent) -> Asset:
        # 1. depuis la stratégie déjà liée
        if intent.strategy_id and intent.strategy and intent.strategy.asset_id:
            return intent.strategy.asset

        # 2. premier asset de position du portefeuille
        first_position = intent.portfolio.positions.select_related("asset").order_by("id").first()
        if first_position and first_position.asset_id:
            return first_position.asset

        # 3. si un univers est défini dans le plan, on prend le premier symbol connu
        asset_universe = (intent.ai_plan or {}).get("asset_universe") or []
        if asset_universe:
            asset = Asset.objects.filter(symbol=asset_universe[0]).first()
            if asset:
                return asset

        raise ValueError(
            "Impossible de déterminer l’asset de la stratégie. "
            "Aucun asset dans le portefeuille et aucun symbole exploitable dans le plan IA."
        )

    @staticmethod
    def _resolve_timeframe_for_intent(intent: TradingIntent) -> Timeframe:
        timeframe_code = (intent.ai_plan or {}).get("timeframe")
        if timeframe_code:
            timeframe = Timeframe.objects.filter(code=timeframe_code).first()
            if timeframe:
                return timeframe

        timeframe = Timeframe.objects.order_by("minutes").first()
        if timeframe:
            return timeframe

        raise ValueError("Aucun timeframe disponible pour créer la stratégie.")

    @staticmethod
    @transaction.atomic
    def analyze(intent: TradingIntent):
        intent.status = "ANALYZING"
        intent.save(update_fields=["status", "updated_at"])

        analysis, plan = AIPlanningService.build_plan(intent)
        intent.ai_analysis = analysis
        intent.ai_plan = plan
        intent.ai_feasibility_score = analysis.get("feasibility_score", 0.0)

        if analysis["feasibility"] == "VERY_LOW" and intent.execution_mode == "LIVE":
            intent.status = "REJECTED"
            intent.rejection_reason = "Objectif trop agressif pour exécution LIVE."
        else:
            intent.status = "PLANNED"
            intent.rejection_reason = ""

        intent.save(update_fields=[
            "ai_analysis",
            "ai_plan",
            "ai_feasibility_score",
            "status",
            "rejection_reason",
            "updated_at",
        ])

        TradingIntentEvent.objects.create(
            intent=intent,
            event_type="ANALYZED",
            title="Analyse IA terminée",
            message=f"Feasibility: {analysis['feasibility']}",
            payload={"analysis": analysis, "plan": plan},
        )
        return intent

    @staticmethod
    @transaction.atomic
    def launch(intent: TradingIntent):
        if intent.status not in ["PLANNED", "APPROVED", "RUNNING"]:
            raise ValueError("Intent non prêt pour lancement.")

        if not intent.ai_plan:
            raise ValueError("Plan IA absent.")

        strategy = intent.strategy
        if not strategy:
            asset = IntentExecutionService._resolve_asset_for_intent(intent)
            timeframe = IntentExecutionService._resolve_timeframe_for_intent(intent)

            strategy = Strategy.objects.create(
                name=f"{intent.title} Strategy",
                strategy_type=intent.ai_plan.get("strategy_type", "HYBRID"),
                status="PAPER" if intent.execution_mode == "PAPER" else "LIVE",
                asset=asset,
                timeframe=timeframe,
                is_active=True,
                is_autonomous=True,
                allow_live_execution=intent.execution_mode == "LIVE",
                min_confidence_threshold=float(intent.ai_plan.get("min_confidence_threshold", 0.7)),
                risk_per_trade_percent=float(intent.ai_plan.get("risk_per_trade_percent", 2.0)),
                parameters=intent.ai_plan,
                description=f"Stratégie générée automatiquement pour l’intention {intent.title}",
            )
            intent.strategy = strategy

        intent.status = "RUNNING"
        intent.started_at = timezone.now()
        intent.expires_at = timezone.now() + timezone.timedelta(days=intent.duration_days)
        intent.save(update_fields=[
            "strategy",
            "status",
            "started_at",
            "expires_at",
            "updated_at",
        ])

        TradingIntentEvent.objects.create(
            intent=intent,
            event_type="STARTED",
            title="Intent lancé",
            message="La mission de trading a démarré.",
            payload={"strategy_id": intent.strategy_id},
        )
        return intent


class IntentMonitoringService:
    @staticmethod
    def refresh_metrics(intent: TradingIntent):
        # Ici on garde la logique portefeuille globale,
        # mais elle peut être affinée plus tard vers les seules positions liées à l’intention.
        positions = Position.objects.filter(
            portfolio=intent.portfolio,
            status="OPEN",
        )

        unrealized = sum((p.pnl or Decimal("0")) for p in positions)
        realized = Decimal("0")

        intent.unrealized_pnl = unrealized
        intent.realized_pnl = realized

        if intent.capital_amount and intent.capital_amount > 0:
            intent.actual_return_percent = float(((realized + unrealized) / intent.capital_amount) * 100)

        if intent.expires_at and timezone.now() >= intent.expires_at and intent.status == "RUNNING":
            intent.status = "COMPLETED"
            intent.ended_at = timezone.now()

        intent.save(update_fields=[
            "unrealized_pnl",
            "realized_pnl",
            "actual_return_percent",
            "status",
            "ended_at",
            "updated_at",
        ])
        return intent