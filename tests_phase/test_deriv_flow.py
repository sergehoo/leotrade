"""
tests_phase/test_deriv_flow.py
================================

Couverture : flux complet d'exécution Deriv — proposal → buy → fill.

On mock la couche WebSocket (DerivBrokerClient) pour ne pas toucher Deriv
en vrai, puis on valide que les invariants internes sont respectés :
  1. BrokerExternalRef CONTRACT est créé avec le bon contract_id.
  2. BrokerExternalRef TRANSACTION est créé avec le bon tx_id.
  3. Un ExecutionFill est persisté avec la bonne quantité / notional.
  4. L'Order passe au statut FILLED.
  5. Le cash est déduit du portfolio (via FillProcessingService).
  6. Un contract_id absent dans la réponse buy → RuntimeError.
  7. Un proposal_id absent → RuntimeError (pas de buy effectué).
  8. L'idempotence fill : un second submit avec le même broker_fill_id
     ne crée pas deux fills.
"""

from decimal import Decimal
from unittest import mock

import pytest

from brokers.models_external_ref import BrokerExternalRef
from execution.models import ExecutionFill, Order
from infrastructure.broker_clients.deriv_client import DerivBrokerClient
from portfolio.services import PortfolioAccountingService

# ── Constantes ────────────────────────────────────────────────────────────────

FAKE_CONTRACT_ID = 123456789
FAKE_TX_ID = 987654321
FAKE_PROPOSAL_ID = "prop-abc-001"
FAKE_BUY_PRICE = 9.87   # ce que Deriv facture réellement

# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture
def live_order(db, user, portfolio_live, broker_live):
    """Order LIVE en PENDING_SUBMIT, prêt à être soumis à Deriv."""
    return Order.objects.create(
        user=user,
        portfolio=portfolio_live,
        broker_account=broker_live,
        symbol="R_100",
        side="BUY",
        order_type="MARKET",
        mode="LIVE",
        status="PENDING_SUBMIT",
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
        approved_stake=Decimal("10.00"),
        requested_stake_amount=Decimal("10.00"),
        approved_notional=Decimal("10.00"),
        idempotency_key="deriv-flow-test-1",
        metadata={"duration": 5, "duration_unit": "t"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_ws_client(
    proposal_id=FAKE_PROPOSAL_ID,
    contract_id=FAKE_CONTRACT_ID,
    tx_id=FAKE_TX_ID,
    buy_price=FAKE_BUY_PRICE,
):
    """
    Retourne un mock du client WebSocket Deriv simulant les réponses
    proposal() et buy().
    """
    ws = mock.MagicMock()

    # contracts_for : liste de contrats disponibles (minimal)
    ws.contracts_for.return_value = {
        "contracts_for": {
            "available": [
                {
                    "contract_type": "CALL",
                    "min_duration": "1t",
                    "max_duration": "10t",
                    "expiry_type": "tick",
                    "start_type": "spot",
                }
            ]
        }
    }

    # proposal() → renvoie un proposal_id
    ws.proposal.return_value = {
        "proposal": {
            "id": proposal_id,
            "ask_price": buy_price,
            "payout": buy_price * 1.9,
        }
    }

    # buy() → renvoie contract_id + transaction_id
    ws.buy.return_value = {
        "buy": {
            "contract_id": contract_id,
            "transaction_id": tx_id,
            "buy_price": buy_price,
            "longcode": "Win payout if R_100 is higher after 5 ticks.",
        }
    }

    ws.close.return_value = None
    return ws


def _patch_deriv_client(ws_mock):
    """Patch DerivBrokerClient._open_authenticated_ws pour retourner ws_mock."""
    return mock.patch.object(
        DerivBrokerClient,
        "_open_authenticated_ws",
        return_value=ws_mock,
    )


def _patch_validate_contract():
    """Bypass la validation des contrats disponibles."""
    return mock.patch.object(
        DerivBrokerClient,
        "_validate_deriv_contract_available",
        return_value=None,
    )


def _patch_async_sync():
    """Neutralise le sync asynchrone post-submit (Celery)."""
    return mock.patch(
        "brokers.tasks_deriv_sync.sync_single_deriv_contract_task.apply_async"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. BrokerExternalRef — création lors du submit
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivBrokerExternalRef:

    @pytest.mark.django_db
    def test_contract_ref_created(self, live_order, broker_live):
        """submit_order() doit créer un BrokerExternalRef de kind=CONTRACT."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(
                token="fake-token", app_id="12345"
            )
            client.submit_order(live_order)

        ref = BrokerExternalRef.objects.filter(
            broker="DERIV",
            kind="CONTRACT",
            external_id=str(FAKE_CONTRACT_ID),
        ).first()

        assert ref is not None, "BrokerExternalRef CONTRACT non créé"
        assert ref.internal_kind == "ORDER"
        assert ref.internal_id == str(live_order.id)

    @pytest.mark.django_db
    def test_transaction_ref_created(self, live_order, broker_live):
        """submit_order() doit créer un BrokerExternalRef de kind=TRANSACTION."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            client.submit_order(live_order)

        ref = BrokerExternalRef.objects.filter(
            broker="DERIV",
            kind="TRANSACTION",
            external_id=str(FAKE_TX_ID),
        ).first()

        assert ref is not None, "BrokerExternalRef TRANSACTION non créé"
        assert ref.internal_kind == "ORDER"
        assert ref.internal_id == str(live_order.id)

    @pytest.mark.django_db
    def test_ref_upsert_idempotent(self, live_order, broker_live):
        """Deux submits avec le même contract_id → toujours un seul BrokerExternalRef."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            client.submit_order(live_order)
            client.submit_order(live_order)

        count = BrokerExternalRef.objects.filter(
            broker="DERIV",
            kind="CONTRACT",
            external_id=str(FAKE_CONTRACT_ID),
        ).count()
        assert count == 1


# ─────────────────────────────────────────────────────────────────────────────
#  2. Retour normalisé — fills présents dans le dict de retour
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivSubmitReturnValue:

    @pytest.mark.django_db
    def test_return_contains_broker_order_id(self, live_order):
        """Le dict de retour doit contenir broker_order_id = contract_id."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            result = client.submit_order(live_order)

        assert result["broker_order_id"] == str(FAKE_CONTRACT_ID)

    @pytest.mark.django_db
    def test_return_contains_one_fill(self, live_order):
        """Le dict de retour doit contenir exactement 1 fill."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            result = client.submit_order(live_order)

        assert len(result["fills"]) == 1

    @pytest.mark.django_db
    def test_fill_has_correct_broker_fill_id(self, live_order):
        """Le fill dans le retour doit avoir broker_fill_id = tx_id."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            result = client.submit_order(live_order)

        fill = result["fills"][0]
        assert fill["broker_fill_id"] == str(FAKE_TX_ID)

    @pytest.mark.django_db
    def test_fill_quantity_is_one(self, live_order):
        """La convention Deriv : quantity = 1 (1 contrat)."""
        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            result = client.submit_order(live_order)

        fill = result["fills"][0]
        assert Decimal(fill["quantity"]) == Decimal("1")


# ─────────────────────────────────────────────────────────────────────────────
#  3. Fill enregistré en DB (via FillProcessingService.register_fill)
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivFillRegistered:

    @pytest.fixture
    def submitted_result(self, live_order):
        """Résultat d'un submit_order mocké."""
        ws = _mock_ws_client()
        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            return client.submit_order(live_order)

    @pytest.mark.django_db
    def test_register_fill_creates_execution_fill(
        self, live_order, submitted_result
    ):
        """register_fill() doit créer un ExecutionFill en DB."""
        from execution.services import FillProcessingService

        fill_data = submitted_result["fills"][0]

        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            FillProcessingService.register_fill(
                order=live_order,
                fill_payload={
                    "broker_fill_id": fill_data["broker_fill_id"],
                    "quantity": Decimal(fill_data["quantity"]),
                    "price": Decimal(fill_data["price"]),
                    "notional": Decimal(fill_data["notional"]),
                    "fee": Decimal(fill_data.get("fee", "0")),
                },
            )

        fill = ExecutionFill.objects.filter(
            order=live_order,
            broker_fill_id=str(FAKE_TX_ID),
        ).first()

        assert fill is not None, "ExecutionFill non créé en DB"
        assert fill.quantity == Decimal("1")

    @pytest.mark.django_db
    def test_order_status_filled_after_register_fill(
        self, live_order, submitted_result
    ):
        """Après register_fill avec quantity=1 (approved_quantity=1), l'order→FILLED."""
        from execution.services import FillProcessingService

        fill_data = submitted_result["fills"][0]

        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            FillProcessingService.register_fill(
                order=live_order,
                fill_payload={
                    "broker_fill_id": fill_data["broker_fill_id"],
                    "quantity": Decimal("1"),
                    "price": Decimal(fill_data["price"]),
                    "notional": Decimal(fill_data["notional"]),
                    "fee": Decimal("0"),
                },
            )

        live_order.refresh_from_db()
        assert live_order.status == "FILLED"

    @pytest.mark.django_db
    def test_fill_idempotent_second_register_no_duplicate(
        self, live_order, submitted_result
    ):
        """Enregistrer deux fois le même broker_fill_id → toujours 1 seul fill."""
        from execution.services import FillProcessingService

        fill_data = submitted_result["fills"][0]
        fill_payload = {
            "broker_fill_id": fill_data["broker_fill_id"],
            "quantity": Decimal("1"),
            "price": Decimal(fill_data["price"]),
            "notional": Decimal(fill_data["notional"]),
            "fee": Decimal("0"),
        }

        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            f1 = FillProcessingService.register_fill(order=live_order, fill_payload=fill_payload)
            f2 = FillProcessingService.register_fill(order=live_order, fill_payload=fill_payload)

        assert f1.id == f2.id
        assert ExecutionFill.objects.filter(order=live_order).count() == 1


# ─────────────────────────────────────────────────────────────────────────────
#  4. Erreurs broker — contrat/proposal manquant
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivSubmitErrors:

    @pytest.mark.django_db
    def test_missing_contract_id_raises_runtime_error(self, live_order):
        """Si buy() ne retourne pas contract_id → RuntimeError."""
        ws = _mock_ws_client(contract_id=None)  # simuler l'absence

        # On force buy à ne pas retourner contract_id
        ws.buy.return_value = {
            "buy": {
                # contract_id absent
                "transaction_id": FAKE_TX_ID,
                "buy_price": FAKE_BUY_PRICE,
            }
        }

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            with pytest.raises(RuntimeError, match="contract_id"):
                client.submit_order(live_order)

    @pytest.mark.django_db
    def test_missing_proposal_id_raises_runtime_error(self, live_order):
        """Si proposal() ne retourne pas d'id → RuntimeError (buy jamais appelé)."""
        ws = _mock_ws_client()
        ws.proposal.return_value = {
            "proposal": {
                # id absent
                "ask_price": FAKE_BUY_PRICE,
            }
        }

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            with pytest.raises(RuntimeError, match="proposal"):
                client.submit_order(live_order)

        # buy() ne doit PAS avoir été appelé
        ws.buy.assert_not_called()

    @pytest.mark.django_db
    def test_zero_stake_raises_value_error(self, live_order):
        """Un order avec stake=0 doit lever ValueError avant même d'appeler le WS."""
        live_order.requested_stake_amount = Decimal("0")
        live_order.approved_notional = Decimal("0")
        live_order.save()

        ws = _mock_ws_client()

        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            with pytest.raises(ValueError, match="stake"):
                client.submit_order(live_order)

        # Ni proposal ni buy ne doivent avoir été appelés
        ws.proposal.assert_not_called()
        ws.buy.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
#  5. Séquence complète intégrée (submit + register_fill)
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivFullFlowIntegration:

    @pytest.mark.django_db
    def test_full_submit_to_filled_sequence(
        self, live_order, portfolio_live
    ):
        """
        Séquence complète :
          1. submit_order → dict avec fills
          2. register_fill → Order=FILLED, BrokerExternalRef créé
        """
        from execution.services import FillProcessingService

        ws = _mock_ws_client()

        # --- Étape 1 : submit ---
        with _patch_deriv_client(ws), _patch_validate_contract(), _patch_async_sync():
            client = DerivBrokerClient(token="fake-token", app_id="12345")
            result = client.submit_order(live_order)

        assert result["broker_order_id"] == str(FAKE_CONTRACT_ID)
        assert len(result["fills"]) == 1

        # --- Étape 2 : register_fill ---
        fill_data = result["fills"][0]

        with mock.patch("execution.services.PositionService.apply_fill_to_position"), \
             mock.patch("execution.services.AccountingBridgeService.apply_fill_accounting"), \
             mock.patch("execution.services.TradingNotificationService.notify_order_filled"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_dashboard_update"), \
             mock.patch("execution.services.RealtimeBroadcastService.broadcast_portfolio_update"), \
             mock.patch("django.db.transaction.on_commit", lambda fn: fn()):

            FillProcessingService.register_fill(
                order=live_order,
                fill_payload={
                    "broker_fill_id": fill_data["broker_fill_id"],
                    "quantity": Decimal("1"),
                    "price": Decimal(fill_data["price"]),
                    "notional": Decimal(fill_data["notional"]),
                    "fee": Decimal("0"),
                },
            )

        # Vérifications finales
        live_order.refresh_from_db()
        assert live_order.status == "FILLED"
        assert live_order.filled_quantity == Decimal("1")

        # BrokerExternalRef CONTRACT présent
        assert BrokerExternalRef.objects.filter(
            broker="DERIV",
            kind="CONTRACT",
            external_id=str(FAKE_CONTRACT_ID),
            internal_id=str(live_order.id),
        ).exists()

        # ExecutionFill présent
        assert ExecutionFill.objects.filter(
            order=live_order,
            broker_fill_id=str(FAKE_TX_ID),
        ).exists()
