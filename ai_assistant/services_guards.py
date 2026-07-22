"""
AssistantRiskValidationService — garde-fous avant toute action sensible.

Blocages (cahier des charges) : KYC non validé (LIVE), broker inactif,
kill switch actif, portefeuille insuffisant. Plus l'aperçu Risk Engine
(RiskGuardService.validate_trade) pour les préparations de trade.

Chaque vérification retourne un dict structuré — jamais d'exception vers
l'assistant : un blocage est une RÉPONSE, pas une erreur.
"""

from __future__ import annotations

import logging
from decimal import Decimal

log = logging.getLogger("lyneci.ai_assistant.guards")


class GuardResult(dict):
    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))


def _block(code: str, message: str) -> GuardResult:
    return GuardResult(ok=False, code=code, message=message)


def _allow(**extra) -> GuardResult:
    return GuardResult(ok=True, code="", message="", **extra)


class AssistantRiskValidationService:
    # ------------------------------------------------------------------
    # Garde-fous unitaires
    # ------------------------------------------------------------------
    @staticmethod
    def check_kyc(user, mode: str) -> GuardResult:
        """KYC approuvé obligatoire pour toute action LIVE."""
        if mode != "LIVE":
            return _allow()
        profile = getattr(user, "kyc_profile", None)
        if profile is None or profile.status != "APPROVED":
            return _block(
                "KYC_REQUIRED",
                "Ton KYC n'est pas validé : les actions LIVE sont bloquées. "
                "Soumets ton dossier depuis le tableau de bord KYC.",
            )
        return _allow()

    @staticmethod
    def check_broker(broker_account) -> GuardResult:
        if broker_account is None:
            return _block("NO_BROKER", "Aucun compte broker configuré. Ajoute-en un depuis la page Brokers.")
        if not broker_account.is_active:
            return _block(
                "BROKER_INACTIVE",
                f"Le compte broker « {broker_account.name} » est inactif — action bloquée.",
            )
        if broker_account.status == "ERROR":
            return _block(
                "BROKER_ERROR",
                f"Le compte broker « {broker_account.name} » est en erreur "
                f"({(broker_account.last_connection_error or 'connexion KO')[:120]}). "
                f"Teste la connexion avant de trader.",
            )
        return _allow()

    @staticmethod
    def check_kill_switch(portfolio) -> GuardResult:
        try:
            from risk.services import RiskGuardService

            if RiskGuardService.has_active_kill_switch(portfolio):
                return _block(
                    "KILL_SWITCH_ACTIVE",
                    f"Le kill switch est actif sur « {portfolio.name} » : "
                    f"aucune nouvelle entrée n'est autorisée tant qu'il n'est pas levé.",
                )
        except Exception:
            log.exception("guards.kill_switch_check_failed")
        return _allow()

    @staticmethod
    def check_funds(portfolio, amount) -> GuardResult:
        available = Decimal(str(portfolio.available_cash or 0))
        needed = Decimal(str(amount or 0))
        if needed <= 0:
            return _block("INVALID_AMOUNT", "Montant invalide : indique un montant strictement positif.")
        if available < needed:
            return _block(
                "INSUFFICIENT_FUNDS",
                f"Cash disponible insuffisant : {available:.2f} $ disponibles "
                f"pour {needed:.2f} $ demandés.",
            )
        return _allow(available=str(available))

    # ------------------------------------------------------------------
    # Pipeline complet pour une préparation de trade
    # ------------------------------------------------------------------
    @classmethod
    def validate_trade_preparation(cls, *, user, portfolio, broker_account,
                                   amount, mode: str) -> GuardResult:
        for guard in (
            lambda: cls.check_broker(broker_account),
            lambda: cls.check_kyc(user, mode),
            lambda: cls.check_kill_switch(portfolio),
            lambda: cls.check_funds(portfolio, amount),
        ):
            result = guard()
            if not result.ok:
                return result
        return _allow()

    # ------------------------------------------------------------------
    # Aperçu Risk Engine (sans exécution)
    # ------------------------------------------------------------------
    @staticmethod
    def risk_preview(*, portfolio, idea, stake_amount) -> dict:
        """Appelle RiskGuardService.validate_trade en mode aperçu et renvoie
        un résumé sérialisable pour AssistantActionRequest.risk_summary."""
        try:
            from risk.services import RiskGuardService

            approval = RiskGuardService.validate_trade(
                portfolio=portfolio,
                symbol=idea.symbol,
                side="BUY" if idea.direction in ("BUY", "CALL") else "SELL",
                requested_stake=Decimal(str(stake_amount)),
                approved_quantity=Decimal("0"),
                approved_notional=Decimal(str(stake_amount)),
                entry_price=Decimal(str(idea.entry_price or 0)),
                stop_loss=Decimal(str(idea.stop_loss)) if idea.stop_loss else None,
                take_profit=Decimal(str(idea.take_profit)) if idea.take_profit else None,
                confidence=Decimal(str(idea.confidence_score or 0)),
                asset=idea.asset,
            )
            return {
                "decision": approval.decision,
                "approved_stake": str(approval.approved_stake),
                "expected_loss": str(approval.expected_loss),
                "expected_gain": str(approval.expected_gain),
                "risk_reward_ratio": str(approval.risk_reward_ratio),
                "blocking_reason": approval.blocking_reason,
                "block_code": approval.block_code,
                "block_severity": approval.block_severity,
            }
        except Exception as exc:
            log.exception("guards.risk_preview_failed")
            return {"decision": "ERROR", "blocking_reason": str(exc)[:300]}
