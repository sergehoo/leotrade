# /Users/ogahserge/Documents/leoTrade/trading/services/execution/deriv_executor.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from brokers.services.deriv import DerivClient, DerivClientError
from portfolio.models import Position
from portfolio.services import PortfolioService, PortfolioAccountingService
from trading.models import DerivContract, Order, TradeExecution


@dataclass
class PortfolioAdvice:
    action: str
    recommended_risk_percent: float = 1.0
    reason: str = ""
    risk_score: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.action} | risk={self.risk_score:.2f} | {self.reason or 'No reason'}"


class DerivExecutorError(Exception):
    pass


class DerivExecutor:
    """
    Exécuteur Deriv moderne.

    Hypothèse métier :
    - approved_quantity représente la mise engagée (stake / cash amount)
    - cette mise est débitée du portefeuille après exécution réussie
    """

    DEFAULT_DURATION = 5
    DEFAULT_DURATION_UNIT = "m"
    ALLOWED_DURATION_UNITS = {"s", "m", "h", "d", "t"}

    def __init__(self, broker_account, portfolio):
        self.broker_account = broker_account
        self.portfolio = portfolio

    def _validate_broker_credentials(self) -> None:
        if not self.broker_account:
            raise DerivExecutorError("Broker account Deriv introuvable.")

        if not self.broker_account.deriv_token:
            raise DerivExecutorError("Token Deriv manquant.")

        if not self.broker_account.deriv_app_id:
            raise DerivExecutorError("App ID Deriv manquant.")

    def _resolve_symbol(self, signal) -> str:
        asset = getattr(getattr(signal, "strategy", None), "asset", None)
        symbol = getattr(asset, "symbol", None)
        if not symbol:
            raise DerivExecutorError("Symbole Deriv introuvable.")
        return str(symbol)

    def _resolve_contract_type(self, signal) -> str:
        asset = getattr(getattr(signal, "strategy", None), "asset", None)
        symbol = str(getattr(asset, "symbol", "") or "").upper()

        is_multiplier_asset = (
                symbol.startswith("CRASH")
                or symbol.startswith("BOOM")
        )

        if is_multiplier_asset:
            if signal.side == "BUY":
                return "MULTUP"
            if signal.side == "SELL":
                return "MULTDOWN"

        if signal.side == "BUY":
            return "CALL"

        if signal.side == "SELL":
            return "PUT"

        raise DerivExecutorError("Signal HOLD non exécutable sur Deriv.")

    def _resolve_duration(self, signal) -> Tuple[int, str]:
        strategy = getattr(signal, "strategy", None)
        params = getattr(strategy, "parameters", {}) or {}

        try:
            duration = int(params.get("deriv_duration", self.DEFAULT_DURATION))
        except (TypeError, ValueError):
            duration = self.DEFAULT_DURATION

        duration = max(1, duration)

        duration_unit = str(
            params.get("deriv_duration_unit", self.DEFAULT_DURATION_UNIT)
        ).lower()

        if duration_unit not in self.ALLOWED_DURATION_UNITS:
            duration_unit = self.DEFAULT_DURATION_UNIT

        return duration, duration_unit

    def _resolve_account_id(self, client: DerivClient) -> Tuple[str, str]:
        accounts_resp = client.list_options_accounts()
        accounts = accounts_resp.get("data", []) or []

        if not accounts:
            raise DerivExecutorError("Aucun compte options Deriv disponible.")

        preferred_type = (self.broker_account.deriv_account_type or "demo").lower()
        selected = None

        for account in accounts:
            if str(account.get("account_type", "")).lower() == preferred_type:
                selected = account
                break

        if not selected:
            selected = accounts[0]

        account_id = selected.get("account_id")
        account_type = selected.get("account_type", "")

        if not account_id:
            raise DerivExecutorError(f"Compte Deriv invalide : {selected}")

        return str(account_id), str(account_type)

    def _compute_expiry(self, duration: int, duration_unit: str):
        now = timezone.now()
        mapping = {
            "s": timedelta(seconds=duration),
            "m": timedelta(minutes=duration),
            "h": timedelta(hours=duration),
            "d": timedelta(days=duration),
            "t": timedelta(minutes=duration),
        }
        return now + mapping.get(duration_unit, timedelta(minutes=duration))

    def _safe_decimal(self, value: Any, default: str = "0") -> Decimal:
        try:
            if value is None:
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    def _safe_price_from_signal(self, signal) -> Decimal:
        return self._safe_decimal(getattr(signal, "price", None), default="0")

    def _normalize_deriv_contract_params(
            self,
            *,
            symbol: str,
            contract_type: str,
            duration: int,
            duration_unit: str,
    ) -> tuple[str, int, str]:
        """
        Normalise les paramètres Deriv avant proposal().

        Objectif :
        - Volatility indices : CALL/PUT avec durée standard possible
        - Crash/Boom : privilégier ticks
        - Jump / Step / Range / Drift : sécuriser durée et unité
        """

        symbol_upper = str(symbol or "").upper().strip()
        duration = max(1, int(duration or self.DEFAULT_DURATION))
        duration_unit = str(duration_unit or self.DEFAULT_DURATION_UNIT).lower()

        if duration_unit not in self.ALLOWED_DURATION_UNITS:
            duration_unit = self.DEFAULT_DURATION_UNIT

        # Crash / Boom indices
        crash_boom_prefixes = (
            "CRASH",
            "BOOM",
            "CRASH_",
            "BOOM_",
        )

        if symbol_upper.startswith(crash_boom_prefixes):
            duration_unit = "t"
            duration = max(duration, 5)

        # Jump indices
        jump_prefixes = (
            "JD",
            "JUMP",
        )

        if symbol_upper.startswith(jump_prefixes):
            duration_unit = "t"
            duration = max(duration, 5)

        # Step indices
        step_prefixes = (
            "STEP",
            "STP",
        )

        if symbol_upper.startswith(step_prefixes):
            duration_unit = "t"
            duration = max(duration, 5)

        # Volatility indices : R_10, R_25, R_50, R_75, R_100, etc.
        volatility_prefixes = (
            "R_",
            "1HZ",
            "HZ",
            "V",
            "VOL",
        )

        if symbol_upper.startswith(volatility_prefixes):
            if duration_unit not in ("t", "s", "m", "h", "d"):
                duration_unit = "m"
            duration = max(duration, 1)

        # Forex Deriv : souvent frxEURUSD, frxGBPUSD, etc.
        if symbol_upper.startswith("FRX"):
            if duration_unit == "t":
                duration_unit = "m"
            duration = max(duration, 1)

        # Commodities Deriv : frxXAUUSD, frxXAGUSD parfois selon mapping
        if "XAU" in symbol_upper or "XAG" in symbol_upper:
            if duration_unit == "t":
                duration_unit = "m"
            duration = max(duration, 1)

        # Sécurité finale
        allowed_contract_types = ("CALL", "PUT", "MULTUP", "MULTDOWN")

        if contract_type not in allowed_contract_types:
            raise DerivExecutorError(
                f"Type de contrat Deriv non supporté pour quick trade : {contract_type}"
            )

        return contract_type, duration, duration_unit

    def _validate_contract_available(self, client, symbol, contract_type):
        resp = client.contracts_for(symbol)
        available = resp.get("contracts_for", {}).get("available", [])

        allowed_types = {
            item.get("contract_type")
            for item in available
            if item.get("contract_type")
        }

        print("DERIV CONTRACTS_FOR DEBUG:", {
            "symbol": symbol,
            "wanted": contract_type,
            "allowed": sorted(allowed_types),
        })

        if contract_type not in allowed_types:
            raise DerivExecutorError(
                f"Contrat {contract_type} non disponible pour {symbol}. "
                f"Contrats disponibles: {', '.join(sorted(allowed_types)) or 'aucun'}"
            )
    @transaction.atomic
    def execute_signal(self, signal, approved_quantity: Decimal) -> Dict[str, Any]:
        self._validate_broker_credentials()

        approved_quantity = self._safe_decimal(approved_quantity, default="0").quantize(Decimal("0.01"))

        if signal.side == "HOLD" or approved_quantity <= 0:
            raise DerivExecutorError("Signal non exécutable.")

        current_balance = self._safe_decimal(
            getattr(self.portfolio, "current_balance", None),
            default="0"
        )
        if current_balance < approved_quantity:
            raise DerivExecutorError(
                f"Solde portefeuille insuffisant. Disponible={current_balance}, requis={approved_quantity}"
            )

        symbol = self._resolve_symbol(signal)
        contract_type = self._resolve_contract_type(signal)
        duration, duration_unit = self._resolve_duration(signal)
        contract_type, duration, duration_unit = self._normalize_deriv_contract_params(
            symbol=symbol,
            contract_type=contract_type,
            duration=duration,
            duration_unit=duration_unit,
        )
        currency = self.broker_account.deriv_currency or "USD"
        signal_price = self._safe_price_from_signal(signal)

        order = Order.objects.create(
            broker_account=self.broker_account,
            portfolio=self.portfolio,
            signal=signal,
            symbol=symbol,
            side="BUY" if signal.side == "BUY" else "SELL",
            order_type="MARKET",
            quantity=approved_quantity,
            price=signal_price,
            stop_loss=getattr(signal, "stop_loss", None),
            take_profit=getattr(signal, "take_profit", None),
            placed_at=timezone.now(),
            status="PENDING",
            notes="Deriv options contract execution",
        )

        client: Optional[DerivClient] = None

        try:
            client = DerivClient(
                token=self.broker_account.deriv_token,
                app_id=str(self.broker_account.deriv_app_id),
            )

            account_id, account_type = self._resolve_account_id(client)
            ws_url = client.get_otp_ws_url(account_id)
            client.connect_with_otp_url(ws_url)
            self._validate_contract_available(client, symbol, contract_type)

            print("DERIV PROPOSAL DEBUG:", {
                "symbol": symbol,
                "amount": str(approved_quantity),
                "contract_type": contract_type,
                "currency": currency,
                "duration": duration,
                "duration_unit": duration_unit,
            })
            proposal = client.proposal(
                underlying_symbol=symbol,
                amount=float(approved_quantity),
                contract_type=contract_type,
                currency=currency,
                duration=None if contract_type in ("MULTUP", "MULTDOWN") else duration,
                duration_unit=None if contract_type in ("MULTUP", "MULTDOWN") else duration_unit,
                basis="stake",
                multiplier=100 if contract_type in ("MULTUP", "MULTDOWN") else None,
            )

            proposal_data = proposal.get("proposal", {}) or {}
            proposal_id = proposal_data.get("id")
            proposal_display_value = self._safe_decimal(
                proposal_data.get("display_value", approved_quantity),
                default=str(approved_quantity),
            )

            if not proposal_id:
                raise DerivExecutorError(f"Proposal ID introuvable : {proposal}")

            buy_response = client.buy(
                proposal_id=str(proposal_id),
                price=float(proposal_display_value),
            )

            buy_data = buy_response.get("buy", {}) or {}
            contract_id = buy_data.get("contract_id")
            transaction_id = buy_data.get("transaction_id")
            buy_price = self._safe_decimal(
                buy_data.get("buy_price", approved_quantity),
                default=str(approved_quantity),
            )

            if not contract_id:
                raise DerivExecutorError(
                    f"Contract ID introuvable après buy : {buy_response}"
                )

            asset = getattr(getattr(signal, "strategy", None), "asset", None)
            if not asset:
                raise DerivExecutorError("Asset introuvable sur la stratégie du signal.")

            position = Position.objects.create(
                portfolio=self.portfolio,
                broker_account=self.broker_account,
                asset=asset,
                symbol=symbol,
                side="LONG" if signal.side == "BUY" else "SHORT",
                quantity=approved_quantity,
                entry_price=buy_price if buy_price > 0 else signal_price,
                current_price=buy_price if buy_price > 0 else signal_price,
                stop_loss=getattr(signal, "stop_loss", None),
                take_profit=getattr(signal, "take_profit", None),
                status="OPEN",
                opened_at=timezone.now(),
            )

            order.external_order_id = str(contract_id)
            order.client_order_id = str(transaction_id) if transaction_id else None
            order.position = position
            order.status = "FILLED"
            order.broker_payload = {
                "account_id": account_id,
                "account_type": account_type,
                "proposal": proposal,
                "buy": buy_response,
            }
            order.save(
                update_fields=[
                    "external_order_id",
                    "client_order_id",
                    "position",
                    "status",
                    "broker_payload",
                    "updated_at",
                ]
            )

            TradeExecution.objects.create(
                order=order,
                execution_price=buy_price if buy_price > 0 else signal_price,
                execution_qty=approved_quantity,
                fee=Decimal("0"),
                fee_asset=currency,
                executed_at=timezone.now(),
                broker_payload=buy_response,
            )

            deriv_contract = DerivContract.objects.create(
                order=order,
                broker_account=self.broker_account,
                portfolio=self.portfolio,
                signal=signal,
                contract_id=str(contract_id),
                transaction_id=str(transaction_id) if transaction_id else None,
                symbol=symbol,
                contract_type=contract_type,
                duration=duration,
                duration_unit=duration_unit,
                currency=currency,
                buy_price=buy_price,
                status="OPEN",
                purchased_at=timezone.now(),
                expires_at=self._compute_expiry(duration, duration_unit),
                proposal_payload=proposal,
                buy_payload=buy_response,
            )

            PortfolioAccountingService.add_ledger_entry(
                portfolio=self.portfolio,
                entry_type="TRADE_EXECUTION",
                amount=-approved_quantity,
                reference_type="ORDER",
                reference_id=str(order.id),
                description=f"Ouverture contrat Deriv {contract_id} sur {symbol}",
            )

            PortfolioService.refresh_portfolio_metrics(self.portfolio)

            # ----------------------------------------------------------------
            # Lier le contrat Deriv à l'ordre interne via BrokerExternalRef.
            # CRITIQUE : sans cette référence, on_open_contract_update() ne
            # peut pas retrouver l'ordre local quand Deriv envoie des mises à
            # jour (l'handler tomberait dans _record_external_only_position).
            # ----------------------------------------------------------------
            try:
                from brokers.models_external_ref import BrokerExternalRef
                BrokerExternalRef.upsert(
                    broker="DERIV",
                    broker_account=self.broker_account,
                    kind="CONTRACT",
                    external_id=str(contract_id),
                    internal_kind="ORDER",
                    internal_id=str(order.id),
                    last_status="open",
                    last_payload={
                        "buy_price": str(buy_price),
                        "contract_type": contract_type,
                        "transaction_id": str(transaction_id) if transaction_id else None,
                    },
                )
            except Exception as ref_exc:
                # Non bloquant : le sync Celery compensera si nécessaire
                import logging as _logging
                _logging.getLogger("leotrade.deriv.executor").warning(
                    "BrokerExternalRef.upsert failed contract_id=%s order_id=%s err=%s",
                    contract_id, order.id, ref_exc,
                )

            # ----------------------------------------------------------------
            # Déclencher la vérification asynchrone du contrat côté broker
            # pour confirmer que le contrat est bien enregistré et ouvert.
            # ----------------------------------------------------------------
            try:
                from brokers.tasks_deriv_sync import sync_single_deriv_contract_task
                sync_single_deriv_contract_task.apply_async(
                    kwargs={
                        "broker_account_id": self.broker_account.id,
                        "contract_id": str(contract_id),
                    },
                    countdown=5,  # laisser 5s à Deriv pour finaliser le contrat
                )
            except Exception as task_exc:
                import logging as _logging
                _logging.getLogger("leotrade.deriv.executor").warning(
                    "sync_single_deriv_contract_task.delay failed contract_id=%s err=%s",
                    contract_id, task_exc,
                )

            signal.status = "EXECUTED"
            signal_updates = ["status", "updated_at"]

            if hasattr(signal, "executed_at"):
                signal.executed_at = timezone.now()
                signal_updates.append("executed_at")

            signal.save(update_fields=signal_updates)

            PortfolioService.refresh_portfolio_metrics(self.portfolio)

            return {
                "order": order,
                "contract": deriv_contract,
                "position": position,
            }

        except DerivClientError as exc:
            order.status = "FAILED"
            order.error_message = str(exc)
            order.save(update_fields=["status", "error_message", "updated_at"])
            raise DerivExecutorError(f"Erreur Deriv API : {exc}") from exc

        except Exception as exc:
            order.status = "FAILED"
            order.error_message = str(exc)
            order.save(update_fields=["status", "error_message", "updated_at"])
            raise DerivExecutorError(str(exc)) from exc

        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass