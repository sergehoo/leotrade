"""
tests_phase/test_sizing_unit_guard.py
=====================================

Garde d'unité entre la quantité interne et le volume broker.

Le défaut couvert ici est une confusion de grandeurs, pas une erreur de
calcul : `PositionSizingService` produit une quantité en unités de
sous-jacent (montant / prix), alors que le champ `volume` de MetaTrader 5
est exprimé en LOTS — 1 lot valant `trade_contract_size` unités.

Soumettre l'une pour l'autre multiplie la taille réelle par
`trade_contract_size` (100 000 sur une paire forex). Ces tests figent le
comportement choisi : REFUSER d'ouvrir plutôt que convertir, tant que
l'unité de `Order.approved_quantity` n'est pas garantie en amont.
"""

from decimal import Decimal

import pytest

from core.precision import normalize_order


# ─────────────────────────────────────────────────────────────────────────────
#  1. L'ampleur réelle du défaut, sur le vrai code de dimensionnement
# ─────────────────────────────────────────────────────────────────────────────

class _Portfolio:
    equity = Decimal("10000.00")
    available_cash = Decimal("10000.00")


class _RiskProfile:
    max_risk_per_trade = Decimal("2.00")


@pytest.mark.django_db
def test_sizing_produces_underlying_units_not_lots():
    """Ancre chiffrée du défaut, sur un cas atteignable sans aucun opt-in.

    Compte de 10 000 USD, USDJPY (classe CORE, donc plafond dur à 0,50 %),
    stop à 50 pips. La quantité produite n'a de sens qu'en unités : lue
    comme des lots, elle vaut 100 000 fois trop.
    """
    from risk.services import PositionSizingService

    result = PositionSizingService.compute(
        portfolio=_Portfolio(),
        risk_profile=_RiskProfile(),
        entry_price=Decimal("157.00"),
        stop_loss=Decimal("156.50"),
        requested_stake=Decimal("10000.00"),
        min_qty=Decimal("0.01"),
        qty_step=Decimal("0.01"),
        instrument_tier="CORE",
    )

    quantity = result.quantity
    contract_size = Decimal("100000")

    # Lue en unités, la position respecte le risque voulu.
    loss_as_units = quantity * result.stop_distance
    assert loss_as_units < _Portfolio.equity * Decimal("0.01"), (
        f"La perte au stop devrait rester sous 1 % de l'équité, vaut {loss_as_units}."
    )

    # Lue en lots, elle ruine le compte plusieurs centaines de fois.
    loss_as_lots = quantity * contract_size * result.stop_distance
    assert loss_as_lots > _Portfolio.equity * 100, (
        "Ce test perd son sens si l'ampleur du défaut change : "
        f"perte en lots = {loss_as_lots}, équité = {_Portfolio.equity}."
    )


@pytest.mark.django_db
def test_broker_min_qty_guard_passes_for_the_wrong_reason():
    """`min_qty` ne rattrape rien : il compare des lots à des unités.

    `volume_min` de MT5 vaut 0,01 LOT. La quantité calculée vaut ~63 UNITÉS.
    63 > 0,01, donc le garde-fou est satisfait — alors que la quantité
    correcte serait 0,0006 lot, bien SOUS le minimum, et aurait dû faire
    refuser l'ordre.
    """
    from risk.services import PositionSizingService

    result = PositionSizingService.compute(
        portfolio=_Portfolio(),
        risk_profile=_RiskProfile(),
        entry_price=Decimal("157.00"),
        stop_loss=Decimal("156.50"),
        requested_stake=Decimal("10000.00"),
        min_qty=Decimal("0.01"),
        qty_step=Decimal("0.01"),
        instrument_tier="CORE",
    )

    min_qty_in_lots = Decimal("0.01")
    quantity_in_lots = result.quantity / Decimal("100000")

    assert result.quantity > min_qty_in_lots, "Le garde-fou actuel est satisfait…"
    assert quantity_in_lots < min_qty_in_lots, (
        "…alors que la quantité correctement convertie est sous le minimum broker."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  2. Borne haute : elle manquait totalement au chemin vivant
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxQuantityBound:
    """Avant ce correctif, `normalize_order` n'avait AUCUNE borne supérieure.

    La seule fonction qui en portait une, `BrokerConstraintService.
    normalize_quantity`, n'a aucun appelant — et elle écrêtait en silence
    au lieu de refuser. Le seul filet restant était le retcode du broker.
    """

    def test_quantity_above_max_is_refused(self):
        result = normalize_order(
            quantity=Decimal("63.69"),
            price=Decimal("157.00"),
            min_qty=Decimal("0.01"),
            qty_step=Decimal("0.01"),
            max_qty=Decimal("100"),
        )
        assert result.ok is True, "63,69 reste sous la borne de 100."

        result = normalize_order(
            quantity=Decimal("6369"),
            price=Decimal("157.00"),
            min_qty=Decimal("0.01"),
            qty_step=Decimal("0.01"),
            max_qty=Decimal("100"),
        )
        assert result.ok is False
        assert "max_qty" in result.reason

    def test_refusal_not_silent_clamping(self):
        """Écrêter transformerait une erreur de dimensionnement en ordre
        valide de taille arbitraire — le pire des deux mondes."""
        result = normalize_order(
            quantity=Decimal("6369"),
            price=Decimal("157.00"),
            min_qty=Decimal("0.01"),
            qty_step=Decimal("0.01"),
            max_qty=Decimal("100"),
        )
        assert result.ok is False
        assert result.quantity != Decimal("100"), "La quantité ne doit pas être écrêtée."

    def test_absent_bound_changes_nothing(self):
        """Rétrocompatibilité : les appelants qui ne passent pas `max_qty`
        gardent exactement le comportement d'avant."""
        for bound in (None, Decimal("0")):
            result = normalize_order(
                quantity=Decimal("999999"),
                price=Decimal("157.00"),
                min_qty=Decimal("0.01"),
                qty_step=Decimal("0.01"),
                max_qty=bound,
            )
            assert result.ok is True, f"max_qty={bound} ne doit poser aucune borne."

    def test_bound_is_never_inherited_from_constraint(self):
        """Une fermeture de position ne doit jamais hériter d'un plafond :
        bloquer une sortie détruit du capital au lieu d'en protéger."""

        class _Constraint:
            min_qty = Decimal("0.01")
            qty_step = Decimal("0.01")
            price_tick = Decimal("0.00001")
            min_notional = Decimal("0")
            max_qty = Decimal("100")

        result = normalize_order(
            quantity=Decimal("6369"),
            price=Decimal("157.00"),
            constraint=_Constraint(),
        )
        assert result.ok is True, (
            "max_qty ne doit pas être lu depuis `constraint` : seul un appelant "
            "qui OUVRE doit le passer explicitement."
        )


# ─────────────────────────────────────────────────────────────────────────────
#  3. Garde d'unité MT5 : refuser d'ouvrir, jamais de fermer
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSymbolInfo:
    def __init__(self, contract_size):
        self.visible = True
        self.volume_min = 0.01
        self.volume_step = 0.01
        self.volume_max = 100.0
        self.point = 0.001
        if contract_size is not _MISSING:
            self.trade_contract_size = contract_size


class _FakeTick:
    ask = 157.001
    bid = 157.000


class _FakeOrder:
    id = 1
    symbol = "USDJPY"
    side = "BUY"
    approved_quantity = Decimal("63.69")
    stop_loss = Decimal("156.50")
    take_profit = None
    idempotency_key = "test-key"


_MISSING = object()


@pytest.fixture
def mt5_client(monkeypatch):
    """Client MT5 instancié sans le SDK, qui n'existe que sous Windows."""
    import contextlib

    from infrastructure.broker_clients import mt5_client as module

    class _FakeMt5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        TRADE_ACTION_DEAL = 1
        TRADE_ACTION_REMOVE = 2
        POSITION_TYPE_BUY = 0
        ORDER_TIME_GTC = 0
        ORDER_FILLING_FOK = 0
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_RETURN = 2

        symbol_info_result = None

        @classmethod
        def symbol_info(cls, _symbol):
            return cls.symbol_info_result

        @staticmethod
        def symbol_info_tick(_symbol):
            return _FakeTick()

        @staticmethod
        def order_send(_request):
            # Le test s'arrête ici : la garde se situe en amont.
            raise AssertionError("ORDER_SENT")

    monkeypatch.setattr(module, "mt5", _FakeMt5)
    monkeypatch.setattr(module, "_mt5_session", lambda _id: contextlib.nullcontext())

    class _Account:
        id = 1

    client = object.__new__(module.MT5BrokerClient)
    client.broker_account = _Account()
    # `__del__` appelle shutdown(), qui lit cet attribut : sans lui, le
    # ramasse-miettes émet une PytestUnraisableExceptionWarning en fin de test.
    client._initialized = False
    return client, _FakeMt5


class TestMT5UnitGuard:

    def test_opening_is_refused_when_one_lot_is_not_one_unit(self, mt5_client):
        """Cas USDJPY : 1 lot = 100 000 unités. Ouvrir serait une erreur x100 000."""
        client, fake = mt5_client
        fake.symbol_info_result = _FakeSymbolInfo(100000.0)

        with pytest.raises(ValueError) as excinfo:
            client.submit_order(_FakeOrder())

        assert "non unitaire" in str(excinfo.value)
        assert "100000" in str(excinfo.value)

    def test_opening_is_refused_when_contract_size_is_unknown(self, mt5_client):
        """Fail-closed : une taille de contrat illisible n'est pas supposée valoir 1."""
        client, fake = mt5_client
        fake.symbol_info_result = _FakeSymbolInfo(None)

        with pytest.raises(ValueError, match="non unitaire"):
            client.submit_order(_FakeOrder())

    def test_opening_is_refused_when_the_attribute_is_absent(self, mt5_client):
        client, fake = mt5_client
        fake.symbol_info_result = _FakeSymbolInfo(_MISSING)

        with pytest.raises(ValueError, match="non unitaire"):
            client.submit_order(_FakeOrder())

    def test_opening_proceeds_when_one_lot_is_one_unit(self, mt5_client):
        """Taille de contrat unitaire : plus d'ambiguïté, la garde laisse passer.

        L'ordre va alors jusqu'à l'envoi — c'est l'AssertionError du faux
        order_send qui le prouve, pas une absence d'erreur.
        """
        client, fake = mt5_client
        fake.symbol_info_result = _FakeSymbolInfo(1.0)

        with pytest.raises(AssertionError, match="ORDER_SENT"):
            client.submit_order(_FakeOrder())

    def test_oversized_order_is_refused_by_the_new_upper_bound(self, mt5_client):
        """Même à taille de contrat unitaire, une quantité au-dessus de
        volume_max ne doit plus partir au broker."""
        client, fake = mt5_client
        fake.symbol_info_result = _FakeSymbolInfo(1.0)

        order = _FakeOrder()
        order.approved_quantity = Decimal("5000")  # volume_max = 100

        with pytest.raises(ValueError, match="max_qty"):
            client.submit_order(order)

    def test_closing_is_never_blocked_by_the_unit_guard(self, mt5_client):
        """Asymétrie délibérée : refuser une ouverture protège le capital,
        refuser une fermeture le détruit. La garde ne porte que sur l'ouverture.
        """
        import inspect

        from infrastructure.broker_clients import mt5_client as module

        source_open = inspect.getsource(module.MT5BrokerClient.submit_order)
        source_close = inspect.getsource(module.MT5BrokerClient.close_position)

        assert "trade_contract_size" in source_open
        assert "trade_contract_size" not in source_close, (
            "close_position ne doit porter aucune garde d'unité : une sortie "
            "bloquée laisse l'utilisateur exposé sans moyen de se dégager."
        )
        assert "max_qty" not in source_close, (
            "close_position ne doit porter aucune borne haute de quantité."
        )
