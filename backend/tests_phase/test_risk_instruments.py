"""
Capital Preservation First — classification d'instruments & politique de risque.

Couverture :
  1. Classifieur : synthétiques Deriv (y compris 1HZ*V et stpRNG que l'ancien
     détecteur manquait), FX majeurs vs exotiques, crypto, actions, indices
     réels, et fail-safe sur instrument inconnu.
  2. Politiques de niveau : plafonds, éligibilité préservation, opt-in.
  3. effective_risk_pct : le plafond de classe ne peut que RÉDUIRE le risque.
  4. Garde-fou validate_trade : opt-in requis + exclusion en mode préservation,
     franchissables par décharge explicite (SOFT).
  5. Sizing : plafond dur de classe appliqué + volatility targeting.
"""

from decimal import Decimal

import pytest

from risk.instruments import (
    InstrumentTier,
    classify,
    effective_risk_pct,
    is_deriv_synthetic,
    policy_for,
    policy_for_tier,
)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Classifieur
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol", [
    "R_10", "R_75", "R_100",
    "1HZ10V", "1HZ100V",          # Volatility 1s — manqués par l'ancien détecteur
    "stpRNG", "stpRNG2",          # Step index — manqué par l'ancien détecteur
    "BOOM500", "BOOM1000", "BOOM300N",
    "CRASH500", "CRASH1000", "CRASH300N",
    "JD10", "JD100",
    "RDBEAR", "RDBULL",
])
def test_deriv_synthetics_detected(symbol):
    assert is_deriv_synthetic(symbol) is True
    assert classify(symbol=symbol) == InstrumentTier.SPECULATIVE


@pytest.mark.parametrize("symbol", ["EURUSD", "AAPL", "BTCUSDT", "XAUUSD", "SPX500"])
def test_non_synthetics_not_flagged(symbol):
    assert is_deriv_synthetic(symbol) is False


def test_synthetic_wins_over_declared_asset_class():
    """asset_class n'est PAS fiable : les synthétiques sont seedés en INDEX.
    Le motif de symbole doit primer."""
    assert classify(symbol="R_75", exchange="DERIV", asset_class="INDEX") == \
        InstrumentTier.SPECULATIVE


def test_deriv_exchange_is_speculative_even_unknown_symbol():
    assert classify(symbol="UNKNOWN_THING", exchange="DERIV") == \
        InstrumentTier.SPECULATIVE


@pytest.mark.parametrize("symbol,expected", [
    ("EURUSD", InstrumentTier.CORE),
    ("USDJPY", InstrumentTier.CORE),
    ("USDTRY", InstrumentTier.VOLATILE),   # exotique
    ("EURTRY", InstrumentTier.VOLATILE),
])
def test_fx_majors_vs_exotics(symbol, expected):
    assert classify(symbol=symbol, exchange="MT5", asset_class="FOREX") == expected


def test_symbol_normalisation():
    """EUR/USD=X doit être reconnu comme le majeur EURUSD."""
    assert classify(symbol="EUR/USD=X", asset_class="FOREX") == InstrumentTier.CORE


@pytest.mark.parametrize("asset_class,expected", [
    ("STOCK", InstrumentTier.CORE),
    ("ETF", InstrumentTier.CORE),
    ("INDEX", InstrumentTier.CORE),
    ("CRYPTO", InstrumentTier.VOLATILE),
    ("COMMODITY", InstrumentTier.VOLATILE),
])
def test_classification_by_asset_class(asset_class, expected):
    assert classify(symbol="XYZ", exchange="NASDAQ", asset_class=asset_class) == expected


def test_unknown_instrument_is_failsafe_restrictive():
    """En préservation du capital, l'inconnu se traite comme dangereux."""
    assert classify(symbol="???", exchange="", asset_class="") == \
        InstrumentTier.SPECULATIVE
    assert classify() == InstrumentTier.SPECULATIVE


@pytest.mark.django_db
def test_classify_accepts_asset_object():
    from market.models import Asset

    asset = Asset.objects.create(
        symbol="R_50", name="Volatility 50", asset_class="INDEX",
        exchange="DERIV", is_active=True,
    )
    assert classify(asset) == InstrumentTier.SPECULATIVE
    assert policy_for(asset).tier == InstrumentTier.SPECULATIVE


# ─────────────────────────────────────────────────────────────────────────────
#  2. Politiques de niveau
# ─────────────────────────────────────────────────────────────────────────────

def test_policy_hierarchy_is_coherent():
    core = policy_for_tier(InstrumentTier.CORE)
    volatile = policy_for_tier(InstrumentTier.VOLATILE)
    spec = policy_for_tier(InstrumentTier.SPECULATIVE)

    # Seul CORE est éligible à la préservation et sans opt-in
    assert core.eligible_for_preservation is True
    assert core.requires_explicit_optin is False
    for p in (volatile, spec):
        assert p.eligible_for_preservation is False
        assert p.requires_explicit_optin is True

    # Les plafonds se resserrent en descendant
    assert core.max_risk_per_trade_pct >= volatile.max_risk_per_trade_pct
    assert core.max_symbol_exposure_pct > volatile.max_symbol_exposure_pct > spec.max_symbol_exposure_pct
    assert core.max_tier_exposure_pct > volatile.max_tier_exposure_pct > spec.max_tier_exposure_pct

    # Le spéculatif porte une disclosure explicite sur l'espérance négative
    assert "NÉGATIVE" in spec.disclosure


def test_unknown_tier_falls_back_to_most_restrictive():
    assert policy_for_tier("N_IMPORTE_QUOI").tier == InstrumentTier.SPECULATIVE
    assert policy_for_tier(None).tier == InstrumentTier.SPECULATIVE


def test_no_policy_allows_more_than_half_percent():
    """Garde-fou blueprint : risque par trade ≤ 0,5 % quelle que soit la classe."""
    from risk.instruments import POLICIES

    for policy in POLICIES.values():
        assert policy.max_risk_per_trade_pct <= Decimal("0.50")


# ─────────────────────────────────────────────────────────────────────────────
#  3. effective_risk_pct — ne peut que réduire
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile_pct,tier,expected", [
    ("1.00", InstrumentTier.CORE, "0.50"),          # plafonné
    ("1.00", InstrumentTier.SPECULATIVE, "0.25"),   # plafonné plus fort
    ("0.10", InstrumentTier.CORE, "0.10"),          # profil plus strict conservé
    ("0.20", InstrumentTier.SPECULATIVE, "0.20"),   # profil plus strict conservé
    ("50.00", InstrumentTier.CORE, "0.50"),         # tentative abusive écrasée
])
def test_effective_risk_only_reduces(profile_pct, tier, expected):
    result = effective_risk_pct(Decimal(profile_pct), policy_for_tier(tier))
    assert result == Decimal(expected)


@pytest.mark.parametrize("bad", [None, "", "abc", -5])
def test_effective_risk_handles_garbage(bad):
    result = effective_risk_pct(bad, policy_for_tier(InstrumentTier.CORE))
    assert result >= Decimal("0")
    assert result <= Decimal("0.50")


# ─────────────────────────────────────────────────────────────────────────────
#  4. Garde-fou validate_trade
# ─────────────────────────────────────────────────────────────────────────────

TRADE = dict(
    side="BUY",
    requested_stake=Decimal("10.00"),
    approved_quantity=Decimal("1"),
    approved_notional=Decimal("10.00"),
    entry_price=Decimal("100.00"),
    stop_loss=Decimal("95.00"),
    take_profit=Decimal("110.00"),
    confidence=Decimal("0.95"),
)


@pytest.mark.django_db
def test_preservation_mode_excludes_speculative(portfolio_paper, risk_profile_paper):
    """Mode préservation ON : un synthétique Deriv est bloqué (SOFT)."""
    from risk.services import RiskGuardService

    risk_profile_paper.preservation_mode = True
    risk_profile_paper.allow_speculative_instruments = True  # opt-in fait…
    risk_profile_paper.save()

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_paper, symbol="R_75", risk_override=False, **TRADE
    )
    # …mais la préservation l'exclut quand même
    assert result.decision == "BLOCK"
    assert result.block_code == "PRESERVATION_MODE_EXCLUDES_INSTRUMENT"
    assert result.block_severity == "SOFT"


@pytest.mark.django_db
def test_speculative_requires_explicit_optin(portfolio_paper, risk_profile_paper):
    from risk.services import RiskGuardService

    risk_profile_paper.preservation_mode = False
    risk_profile_paper.allow_speculative_instruments = False
    risk_profile_paper.save()

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_paper, symbol="R_75", risk_override=False, **TRADE
    )
    assert result.decision == "BLOCK"
    assert result.block_code == "INSTRUMENT_TIER_NOT_ENABLED"
    assert result.block_severity == "SOFT"


@pytest.mark.django_db
def test_speculative_allowed_when_optin_and_no_preservation(portfolio_paper, risk_profile_paper):
    from risk.services import RiskGuardService

    risk_profile_paper.preservation_mode = False
    risk_profile_paper.allow_speculative_instruments = True
    risk_profile_paper.save()

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_paper, symbol="R_75", risk_override=False, **TRADE
    )
    assert result.decision == "APPROVE"
    assert result.payload["instrument_tier"] == InstrumentTier.SPECULATIVE


@pytest.mark.django_db
def test_core_instrument_passes_in_preservation_mode(portfolio_paper, risk_profile_paper):
    """Un instrument CORE passe sans opt-in, préservation activée."""
    from market.models import Asset
    from risk.services import RiskGuardService

    asset = Asset.objects.create(
        symbol="EURUSD", name="Euro Dollar", asset_class="FOREX",
        exchange="MT5", is_active=True,
    )
    risk_profile_paper.preservation_mode = True
    risk_profile_paper.require_stop_loss = False
    risk_profile_paper.save()

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_paper, symbol="EURUSD", asset=asset,
        risk_override=False, **TRADE
    )
    assert result.decision == "APPROVE"
    assert result.payload["instrument_tier"] == InstrumentTier.CORE


@pytest.mark.django_db
def test_tier_block_is_overridable_with_decharge(portfolio_paper, risk_profile_paper, user):
    """Le blocage de classe est SOFT : franchissable par décharge tracée."""
    from risk.services import RiskGuardService

    risk_profile_paper.preservation_mode = True
    risk_profile_paper.save()

    result = RiskGuardService.validate_trade(
        portfolio=portfolio_paper, symbol="R_75",
        risk_override=True,
        risk_override_reason="opt-in explicite spéculatif",
        risk_override_user_id=user.id,
        **TRADE
    )
    assert result.decision == "APPROVE"
    applied = result.payload["risk_override"].get("applied_to", [])
    assert any(
        e["code"] in ("PRESERVATION_MODE_EXCLUDES_INSTRUMENT",
                      "INSTRUMENT_TIER_NOT_ENABLED")
        for e in applied
    )


# ─────────────────────────────────────────────────────────────────────────────
#  5. Sizing — plafond de classe + volatility targeting
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sizing_applies_tier_hard_cap(portfolio_paper, risk_profile_paper):
    """CORE plafonne à 0,50 % : la quantité doit être moitié de celle à 1 %."""
    from risk.services import PositionSizingService

    risk_profile_paper.max_risk_per_trade = Decimal("1.00")
    risk_profile_paper.save()

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("90"),
        requested_stake=Decimal("10000"),
    )
    uncapped = PositionSizingService.compute(**common)
    capped = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.CORE)

    assert capped.quantity == uncapped.quantity / 2
    assert "Plafond classe CORE" in capped.reason


@pytest.mark.django_db
def test_sizing_speculative_cap_is_tighter_than_core(portfolio_paper, risk_profile_paper):
    from risk.services import PositionSizingService

    risk_profile_paper.max_risk_per_trade = Decimal("1.00")
    risk_profile_paper.save()

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("90"),
        requested_stake=Decimal("10000"),
    )
    core = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.CORE)
    spec = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.SPECULATIVE)

    assert spec.quantity < core.quantity


@pytest.mark.django_db
def test_sizing_tier_cap_never_increases_risk(portfolio_paper, risk_profile_paper):
    """Un profil déjà plus strict que la classe n'est pas relevé."""
    from risk.services import PositionSizingService

    risk_profile_paper.max_risk_per_trade = Decimal("0.10")
    risk_profile_paper.save()

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("90"),
        requested_stake=Decimal("10000"),
    )
    plain = PositionSizingService.compute(**common)
    capped = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.CORE)

    assert capped.quantity == plain.quantity
    assert "Plafond classe" not in capped.reason


@pytest.mark.django_db
def test_volatility_targeting_bounds_quantity(portfolio_paper, risk_profile_paper):
    """Un ATR élevé doit réduire la quantité sous le sizing stop-based."""
    from risk.services import PositionSizingService

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("99.9"),  # stop très serré
        requested_stake=Decimal("10000"),
    )
    without_vol = PositionSizingService.compute(**common)
    with_vol = PositionSizingService.compute(
        **common, atr=Decimal("5"), target_vol_pct=Decimal("1.00"),
    )

    assert with_vol.quantity < without_vol.quantity
    assert "Volatility targeting actif" in with_vol.reason


@pytest.mark.django_db
def test_volatility_targeting_inactive_without_atr(portfolio_paper, risk_profile_paper):
    from risk.services import PositionSizingService

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("90"),
        requested_stake=Decimal("1000"),
    )
    baseline = PositionSizingService.compute(**common)
    with_zero_atr = PositionSizingService.compute(**common, atr=Decimal("0"))

    assert with_zero_atr.quantity == baseline.quantity
    assert "Volatility targeting" not in with_zero_atr.reason


# ─────────────────────────────────────────────────────────────────────────────
#  6. Régression : le garde-fou de classe ne doit PAS masquer le kill switch
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tier_gate_does_not_mask_kill_switch_escalation(portfolio_live, risk_profile_live):
    """Les blocs de perte (jour/semaine/mois/drawdown) déclenchent le kill
    switch en EFFET DE BORD. Le garde-fou de classe d'instrument doit être
    évalué APRÈS eux : sinon un retour anticipé masquerait une protection
    bien plus forte.

    Scénario : limite de perte journalière dépassée ET instrument spéculatif
    non autorisé. Le kill switch doit tout de même se déclencher.
    """
    from risk.models import DailyRiskState
    from risk.services import RiskGuardService

    # Instrument spéculatif NON autorisé + préservation ON => bloc 9bis actif
    risk_profile_live.preservation_mode = True
    risk_profile_live.allow_speculative_instruments = False
    risk_profile_live.max_daily_loss = Decimal("1.00")
    risk_profile_live.kill_switch_enabled = True
    risk_profile_live.save()

    # Perte journalière au-delà de la limite (equity_open > equity réelle)
    DailyRiskState.objects.update_or_create(
        portfolio=portfolio_live,
        day=__import__("django.utils.timezone", fromlist=["timezone"]).localdate(),
        defaults={
            "equity_open": Decimal("10500.00"),
            "equity_current": Decimal("10000.00"),
        },
    )

    assert RiskGuardService.has_active_kill_switch(portfolio_live) is False

    RiskGuardService.validate_trade(
        portfolio=portfolio_live, symbol="R_75", risk_override=False, **TRADE
    )

    # La protection forte a bien été déclenchée, malgré le blocage de classe
    assert RiskGuardService.has_active_kill_switch(portfolio_live) is True


# ─────────────────────────────────────────────────────────────────────────────
#  7. Régressions issues de la revue adversariale
# ─────────────────────────────────────────────────────────────────────────────

def test_all_seeded_deriv_synthetics_are_speculative():
    """Verrou anti-régression : TOUS les synthétiques réellement seedés doivent
    ressortir SPECULATIVE. STEPINDEX (le Step index de cette plateforme)
    ressortait CORE — donc éligible préservation — ce qui présentait un
    instrument à espérance négative comme sûr."""
    import ast
    import re as _re

    src = open("market/management/commands/seed_market_assets.py").read()
    block = _re.search(r"DERIV_SYNTHETIC = (\[.*?\n    \])", src, _re.S).group(1)
    symbols = [entry[0] for entry in ast.literal_eval(block)]

    assert len(symbols) >= 20, "liste de seed inattendue"
    mal_classes = [
        s for s in symbols
        if classify(symbol=s, asset_class="INDEX") != InstrumentTier.SPECULATIVE
    ]
    assert mal_classes == [], f"synthétiques mal classés : {mal_classes}"


@pytest.mark.parametrize("symbol", [
    "EURUSDm", "EURUSD.a", "EURUSD_raw", "EURUSD-ECN", "GBPUSDc", "USDJPY.pro",
])
def test_broker_suffixed_fx_majors_stay_core(symbol):
    """Les suffixes de courtier ne doivent pas éjecter un majeur FX de CORE
    (sinon la paire la plus liquide du monde est bloquée en mode préservation)."""
    assert classify(symbol=symbol) == InstrumentTier.CORE


def test_stepindex_is_speculative():
    assert is_deriv_synthetic("STEPINDEX") is True
    assert classify(symbol="STEPINDEX", asset_class="INDEX") == InstrumentTier.SPECULATIVE


@pytest.mark.django_db
def test_vol_budget_derives_from_tier_cap(portfolio_paper, risk_profile_paper):
    """Sans target_vol_pct explicite, le budget de volatilité doit suivre le
    risque EFFECTIF (plafonné par la classe), pas un 1 % figé : sinon un
    mouvement d'1 ATR coûte 4x le plafond d'un instrument SPECULATIVE."""
    from risk.services import PositionSizingService

    risk_profile_paper.max_risk_per_trade = Decimal("1.00")
    risk_profile_paper.save()

    common = dict(
        portfolio=portfolio_paper, risk_profile=risk_profile_paper,
        entry_price=Decimal("100"), stop_loss=Decimal("99.9"),
        requested_stake=Decimal("10000"), atr=Decimal("5"),
    )
    spec = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.SPECULATIVE)
    core = PositionSizingService.compute(**common, instrument_tier=InstrumentTier.CORE)

    # Budget dérivé : SPECULATIVE (0,25 %) borne plus fort que CORE (0,50 %)
    assert spec.quantity < core.quantity
    equity = Decimal(str(portfolio_paper.equity))
    cout_1_atr = spec.quantity * Decimal("5")
    assert cout_1_atr <= equity * Decimal("0.0025") + Decimal("0.01")


@pytest.mark.django_db
def test_optin_fields_are_editable_and_audited(user, portfolio_paper):
    """Le message de blocage invite à activer la classe dans le profil : ce
    chemin doit exister, et passer par le mutateur audité."""
    from risk.models import RiskAuditLog
    from risk.services_control import RiskSettingsUpdateService

    for field in ("preservation_mode", "allow_volatile_instruments",
                  "allow_speculative_instruments"):
        assert field in RiskSettingsUpdateService.EDITABLE_FIELDS

    result = RiskSettingsUpdateService.update(
        user=user, portfolio=portfolio_paper,
        changes={"allow_speculative_instruments": True, "preservation_mode": False},
    )
    assert result["ok"]
    from risk.services import RiskGuardService
    profile = RiskGuardService.get_default_profile(portfolio_paper)
    assert profile.allow_speculative_instruments is True
    assert profile.preservation_mode is False
    assert RiskAuditLog.objects.filter(
        portfolio=portfolio_paper, action="RISK_SETTINGS_UPDATE",
    ).exists()


@pytest.mark.django_db
def test_deriv_stake_is_capped_by_risk_profile(portfolio_paper, risk_profile_paper):
    """Contournement majeur corrigé : la branche Deriv n'appelait pas le sizing,
    donc max_risk_per_trade n'était JAMAIS appliqué sur les instruments à
    espérance négative. Sur ces contrats la mise EST la perte maximale."""
    from trading.services.trade_idea_execution import TradeIdeaExecutionService

    # équité 10 000, plafond SPECULATIVE 0,25 % => mise max 25
    sizing = TradeIdeaExecutionService._build_deriv_sizing(
        Decimal("400"),
        portfolio=portfolio_paper,
        risk_profile=risk_profile_paper,
        instrument_tier=InstrumentTier.SPECULATIVE,
    )
    assert sizing.notional == Decimal("25.00")
    assert sizing.requested_stake == Decimal("400")
    assert "plafonnée" in sizing.reason


@pytest.mark.django_db
def test_deriv_stake_under_cap_is_untouched(portfolio_paper, risk_profile_paper):
    from trading.services.trade_idea_execution import TradeIdeaExecutionService

    sizing = TradeIdeaExecutionService._build_deriv_sizing(
        Decimal("10"),
        portfolio=portfolio_paper,
        risk_profile=risk_profile_paper,
        instrument_tier=InstrumentTier.SPECULATIVE,
    )
    assert sizing.notional == Decimal("10")
    assert "plafonnée" not in sizing.reason


def test_deriv_sizing_backward_compatible_without_profile():
    """Appel legacy sans portfolio/profile : comportement inchangé."""
    from trading.services.trade_idea_execution import TradeIdeaExecutionService

    sizing = TradeIdeaExecutionService._build_deriv_sizing(Decimal("50"))
    assert sizing.quantity == Decimal("1")
    assert sizing.notional == Decimal("50")
