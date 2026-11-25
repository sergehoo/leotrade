"""
tests_phase/test_risk_override_audit.py
========================================

Couverture : modèle RiskOverrideAudit + hook dans validate_trade().

Scénarios :
  1. validate_trade() avec risk_override=True + résultat APPROVE →
     un RiskOverrideAudit est créé en DB.
  2. validate_trade() avec risk_override=False → aucun audit créé.
  3. validate_trade() avec risk_override=True + résultat BLOCK HARD →
     aucun audit créé (on n'audite que les overrides effectifs).
  4. Les champs ip_address, user_agent, reason sont bien persistés.
  5. codes_bypassed contient exactement les codes SOFT franchis.
  6. profile_snapshot capture les valeurs clés du profil au moment de l'appel.
  7. RiskOverrideAudit.record() est fail-safe : une exception interne
     ne remonte pas à l'appelant.
  8. Admin : has_add/change/delete_permission → False.
  9. Export CSV : la réponse contient bien les en-têtes attendus.
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.admin.sites import AdminSite
from django.utils import timezone

from risk.models import RiskOverrideAudit
from risk.services import RiskGuardService

# ── Paramètres de trade de base ───────────────────────────────────────────────

BASE_TRADE = dict(
    symbol="R_100",
    side="BUY",
    requested_stake=Decimal("10.00"),
    approved_quantity=Decimal("1"),
    approved_notional=Decimal("10.00"),
    entry_price=Decimal("100.00"),
    stop_loss=None,
    take_profit=Decimal("110.00"),
    confidence=Decimal("0.95"),
)


def _validate(portfolio, override=False, **kwargs):
    return RiskGuardService.validate_trade(
        portfolio=portfolio,
        risk_override=override,
        risk_override_reason=kwargs.pop("reason", "raison de test"),
        risk_override_user_id=kwargs.pop("user_id", 1),
        risk_override_ip=kwargs.pop("ip", "192.168.1.1"),
        risk_override_user_agent=kwargs.pop("ua", "TestBrowser/1.0"),
        **{**BASE_TRADE, **kwargs},
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. Audit créé quand override=True + APPROVE
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditCreatedOnOverride:

    @pytest.mark.django_db
    def test_audit_created_on_approve_with_override(
        self, portfolio_paper, risk_profile_paper
    ):
        """Un RiskOverrideAudit est créé lorsque override=True et résultat=APPROVE."""
        assert RiskOverrideAudit.objects.count() == 0

        result = _validate(portfolio_paper, override=True)

        assert result.decision == "APPROVE"
        assert RiskOverrideAudit.objects.count() == 1

    @pytest.mark.django_db
    def test_audit_links_correct_portfolio(
        self, portfolio_paper, risk_profile_paper
    ):
        """L'audit pointe vers le bon portfolio."""
        _validate(portfolio_paper, override=True)

        audit = RiskOverrideAudit.objects.first()
        assert audit.portfolio_id == portfolio_paper.id

    @pytest.mark.django_db
    def test_audit_links_correct_user(
        self, user, portfolio_paper, risk_profile_paper
    ):
        """L'audit enregistre le bon user_id (FK réelle vers auth_user)."""
        _validate(portfolio_paper, override=True, user_id=user.id)

        audit = RiskOverrideAudit.objects.first()
        assert audit.user_id == user.id

    @pytest.mark.django_db
    def test_audit_records_symbol_and_side(
        self, portfolio_paper, risk_profile_paper
    ):
        """L'audit enregistre le symbole et le sens du trade."""
        _validate(portfolio_paper, override=True)

        audit = RiskOverrideAudit.objects.first()
        assert audit.symbol == "R_100"
        assert audit.side == "BUY"


# ─────────────────────────────────────────────────────────────────────────────
#  2. Pas d'audit quand override=False
# ─────────────────────────────────────────────────────────────────────────────

class TestNoAuditWithoutOverride:

    @pytest.mark.django_db
    def test_no_audit_when_override_false(
        self, portfolio_paper, risk_profile_paper
    ):
        """Aucun audit si risk_override=False, même si le trade est approuvé."""
        _validate(portfolio_paper, override=False)

        assert RiskOverrideAudit.objects.count() == 0


# ─────────────────────────────────────────────────────────────────────────────
#  3. Pas d'audit si le résultat est BLOCK HARD (override ignoré)
# ─────────────────────────────────────────────────────────────────────────────

class TestNoAuditOnHardBlock:

    @pytest.mark.django_db
    def test_no_audit_on_hard_block_kill_switch(
        self, portfolio_live, risk_profile_live
    ):
        """Si le résultat est BLOCK HARD (kill switch), aucun audit n'est persisté."""
        from risk.models import KillSwitchEvent
        KillSwitchEvent.objects.create(
            portfolio=portfolio_live,
            reason_code="DAILY_LOSS_LIMIT",
            reason="test",
            is_active=True,
            triggered_at=timezone.now(),
        )

        result = _validate(portfolio_live, override=True)

        assert result.decision == "BLOCK"
        assert result.block_severity == "HARD"
        assert RiskOverrideAudit.objects.count() == 0

    @pytest.mark.django_db
    def test_no_audit_on_hard_block_short_forbidden(
        self, portfolio_paper, risk_profile_paper
    ):
        """SHORT_FORBIDDEN est HARD → aucun audit même avec override=True."""
        risk_profile_paper.allow_short = False
        risk_profile_paper.save()

        result = RiskGuardService.validate_trade(
            portfolio=portfolio_paper,
            symbol="R_100",
            side="SELL",
            requested_stake=Decimal("10.00"),
            approved_quantity=Decimal("1"),
            approved_notional=Decimal("10.00"),
            entry_price=Decimal("100.00"),
            stop_loss=None,
            take_profit=Decimal("90.00"),
            confidence=Decimal("0.95"),
            risk_override=True,
            risk_override_reason="force short",
            risk_override_user_id=1,
        )

        assert result.decision == "REJECT"
        assert result.block_severity == "HARD"
        assert RiskOverrideAudit.objects.count() == 0


# ─────────────────────────────────────────────────────────────────────────────
#  4. Champs réseau et raison persistés correctement
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditFieldsPersisted:

    @pytest.mark.django_db
    def test_ip_address_persisted(self, portfolio_paper, risk_profile_paper):
        """L'IP est bien stockée dans l'audit."""
        _validate(portfolio_paper, override=True, ip="10.0.0.42")

        audit = RiskOverrideAudit.objects.first()
        assert audit.ip_address == "10.0.0.42"

    @pytest.mark.django_db
    def test_user_agent_persisted(self, portfolio_paper, risk_profile_paper):
        """Le user_agent est bien stocké."""
        _validate(portfolio_paper, override=True, ua="Mozilla/5.0 LeoTrade-Test")

        audit = RiskOverrideAudit.objects.first()
        assert "LeoTrade-Test" in audit.user_agent

    @pytest.mark.django_db
    def test_reason_persisted(self, portfolio_paper, risk_profile_paper):
        """La raison est stockée telle quelle."""
        _validate(portfolio_paper, override=True, reason="Je suis sûr de mon analyse.")

        audit = RiskOverrideAudit.objects.first()
        assert audit.reason == "Je suis sûr de mon analyse."

    @pytest.mark.django_db
    def test_overridden_at_is_recent(self, portfolio_paper, risk_profile_paper):
        """overridden_at est dans les 5 dernières secondes."""
        before = timezone.now()
        _validate(portfolio_paper, override=True)
        after = timezone.now()

        audit = RiskOverrideAudit.objects.first()
        assert before <= audit.overridden_at <= after


# ─────────────────────────────────────────────────────────────────────────────
#  5. codes_bypassed contient exactement les codes SOFT franchis
# ─────────────────────────────────────────────────────────────────────────────

class TestCodesBypassed:

    @pytest.mark.django_db
    def test_codes_bypassed_empty_when_no_soft_block(
        self, portfolio_paper, risk_profile_paper
    ):
        """Si aucun blocage SOFT n'est déclenché, codes_bypassed = []."""
        _validate(portfolio_paper, override=True)

        audit = RiskOverrideAudit.objects.first()
        assert audit.codes_bypassed == []

    @pytest.mark.django_db
    def test_codes_bypassed_contains_ai_confidence(
        self, portfolio_paper, risk_profile_paper
    ):
        """AI_CONFIDENCE_TOO_LOW franchi → présent dans codes_bypassed."""
        risk_profile_paper.min_confidence = Decimal("0.99")
        risk_profile_paper.save()

        _validate(portfolio_paper, override=True, confidence=Decimal("0.50"))

        audit = RiskOverrideAudit.objects.first()
        assert "AI_CONFIDENCE_TOO_LOW" in audit.codes_bypassed

    @pytest.mark.django_db
    def test_codes_bypassed_contains_max_open_positions(
        self, portfolio_live, risk_profile_live
    ):
        """MAX_OPEN_POSITIONS franchi → présent dans codes_bypassed."""
        risk_profile_live.max_open_positions = 1
        risk_profile_live.save()

        with mock.patch.object(RiskGuardService, "open_positions_count", return_value=1):
            _validate(portfolio_live, override=True)

        audit = RiskOverrideAudit.objects.first()
        assert "MAX_OPEN_POSITIONS" in audit.codes_bypassed


# ─────────────────────────────────────────────────────────────────────────────
#  6. profile_snapshot capture les valeurs clés
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileSnapshot:

    @pytest.mark.django_db
    def test_snapshot_contains_key_fields(self, portfolio_paper, risk_profile_paper):
        """Le snapshot contient les champs clés du profil."""
        _validate(portfolio_paper, override=True)

        audit = RiskOverrideAudit.objects.first()
        snap = audit.profile_snapshot

        assert "max_daily_loss" in snap
        assert "max_weekly_loss" in snap
        assert "max_open_positions" in snap
        assert "allow_live_trading" in snap
        assert "kill_switch_enabled" in snap

    @pytest.mark.django_db
    def test_snapshot_reflects_profile_at_time_of_call(
        self, portfolio_paper, risk_profile_paper
    ):
        """Le snapshot reflète les valeurs du profil AU MOMENT de l'appel,
        pas après une éventuelle modification ultérieure."""
        risk_profile_paper.max_daily_loss = Decimal("7.77")
        risk_profile_paper.save()

        _validate(portfolio_paper, override=True)

        # Modifier le profil après l'override
        risk_profile_paper.max_daily_loss = Decimal("0.01")
        risk_profile_paper.save()

        audit = RiskOverrideAudit.objects.first()
        # Comparaison en Decimal : le snapshot sérialise avec les décimales du champ ("7.7700")
        assert Decimal(audit.profile_snapshot["max_daily_loss"]) == Decimal("7.77")


# ─────────────────────────────────────────────────────────────────────────────
#  7. RiskOverrideAudit.record() fail-safe
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordFailSafe:

    @pytest.mark.django_db
    def test_record_returns_none_on_db_error(self, portfolio_paper, risk_profile_paper):
        """Si la création DB échoue, record() retourne None sans lever d'exception."""
        with mock.patch(
            "risk.models.RiskOverrideAudit.objects.create",
            side_effect=Exception("DB unavailable"),
        ):
            result = RiskOverrideAudit.record(
                user_id=1,
                portfolio=portfolio_paper,
                symbol="R_100",
                side="BUY",
                requested_stake=Decimal("10.00"),
                codes_bypassed=[],
                reason="test",
                ip_address="127.0.0.1",
                user_agent="test",
                profile_snapshot={},
            )

        assert result is None  # pas d'exception, juste None

    @pytest.mark.django_db
    def test_validate_trade_does_not_raise_on_audit_failure(
        self, portfolio_paper, risk_profile_paper
    ):
        """Si RiskOverrideAudit.record() échoue internement, validate_trade()
        ne lève aucune exception — le trade continue."""
        with mock.patch(
            "risk.models.RiskOverrideAudit.record",
            side_effect=Exception("Simulated audit failure"),
        ):
            # Aucune exception ne doit remonter
            result = _validate(portfolio_paper, override=True)

        # Le trade est quand même approuvé
        assert result.decision == "APPROVE"


# ─────────────────────────────────────────────────────────────────────────────
#  8. Admin : permissions read-only
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminReadOnly:

    def test_has_add_permission_false(self):
        from risk.admin import RiskOverrideAuditAdmin
        site = AdminSite()
        admin_obj = RiskOverrideAuditAdmin(RiskOverrideAudit, site)
        assert admin_obj.has_add_permission(request=None) is False

    def test_has_change_permission_false(self):
        from risk.admin import RiskOverrideAuditAdmin
        site = AdminSite()
        admin_obj = RiskOverrideAuditAdmin(RiskOverrideAudit, site)
        assert admin_obj.has_change_permission(request=None) is False

    def test_has_delete_permission_false(self):
        from risk.admin import RiskOverrideAuditAdmin
        site = AdminSite()
        admin_obj = RiskOverrideAuditAdmin(RiskOverrideAudit, site)
        assert admin_obj.has_delete_permission(request=None) is False


# ─────────────────────────────────────────────────────────────────────────────
#  9. Export CSV — en-têtes et contenu de base
# ─────────────────────────────────────────────────────────────────────────────

class TestCsvExport:

    @pytest.mark.django_db
    def test_csv_export_contains_required_headers(
        self, portfolio_paper, risk_profile_paper
    ):
        """L'export CSV de l'admin contient les colonnes réglementaires."""
        from django.test import RequestFactory
        from risk.admin import _export_override_audit_csv, RiskOverrideAuditAdmin

        # Créer un enregistrement d'audit
        RiskOverrideAudit.objects.create(
            user_id=None,
            portfolio=portfolio_paper,
            symbol="R_100",
            side="BUY",
            requested_stake=Decimal("10.00"),
            codes_bypassed=["MAX_OPEN_POSITIONS"],
            reason="test csv",
            ip_address="10.0.0.1",
            user_agent="TestAgent/1.0",
            profile_snapshot={"max_daily_loss": "5.00"},
            overridden_at=timezone.now(),
        )

        site = AdminSite()
        admin_obj = RiskOverrideAuditAdmin(RiskOverrideAudit, site)
        request = RequestFactory().get("/")
        queryset = RiskOverrideAudit.objects.all()

        response = _export_override_audit_csv(admin_obj, request, queryset)

        assert response.status_code == 200
        content = response.content.decode("utf-8-sig")  # retire le BOM

        # En-têtes obligatoires pour l'archivage légal
        for col in [
            "id", "overridden_at", "user_email", "portfolio_name",
            "symbol", "side", "codes_bypassed", "reason",
            "ip_address", "user_agent", "profile_snapshot",
        ]:
            assert col in content, f"Colonne manquante dans le CSV : {col}"

    @pytest.mark.django_db
    def test_csv_export_contains_audit_row(
        self, portfolio_paper, risk_profile_paper
    ):
        """L'export CSV contient bien une ligne pour chaque enregistrement."""
        from django.test import RequestFactory
        from risk.admin import _export_override_audit_csv, RiskOverrideAuditAdmin

        RiskOverrideAudit.objects.create(
            portfolio=portfolio_paper,
            symbol="EURUSD",
            side="BUY",
            requested_stake=Decimal("50.00"),
            codes_bypassed=["DAILY_LOSS_LIMIT"],
            reason="J'assume le risque.",
            ip_address="172.16.0.5",
            user_agent="Mozilla/5.0",
            profile_snapshot={},
            overridden_at=timezone.now(),
        )

        site = AdminSite()
        admin_obj = RiskOverrideAuditAdmin(RiskOverrideAudit, site)
        request = RequestFactory().get("/")
        queryset = RiskOverrideAudit.objects.all()

        response = _export_override_audit_csv(admin_obj, request, queryset)
        content = response.content.decode("utf-8-sig")
        lines = [l for l in content.splitlines() if l.strip()]

        # 1 ligne d'en-tête + 1 ligne de données
        assert len(lines) == 2
        assert "EURUSD" in content
        assert "DAILY_LOSS_LIMIT" in content
        assert "J'assume le risque." in content
