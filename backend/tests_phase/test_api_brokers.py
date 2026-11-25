"""
tests_phase/test_api_brokers.py
===============================

Contrat de l'API brokers v1.

L'enjeu central de ce domaine n'est pas le CRUD : c'est qu'un secret broker
qui entre ne ressorte jamais, et qu'on n'ouvre pas une porte vers l'argent
réel sans KYC. Ces deux propriétés sont testées en premier et sur toutes
les routes, pas seulement sur celle qu'on vient d'écrire.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from brokers.models import BrokerAccount, BrokerCredential

User = get_user_model()

PASSWORD = "StrongPass123!"

# Valeurs sentinelles : si l'une d'elles apparaît dans une réponse HTTP,
# c'est une fuite, quel que soit le champ qui la porte.
SECRET_VALUES = {
    "api_key": "AK-live-7f3c2a91",
    "api_secret": "AS-live-be41d0c8",
    "password": "mt5-terminal-pass",
    "deriv_token": "a1-DERIVTOKEN-xyz",
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_throttle_bucket():
    """Le throttling est réellement actif sur ces routes (scope `sensitive`).

    On vide le compteur entre les tests plutôt que de désactiver la
    protection : `SimpleRateThrottle.THROTTLE_RATES` est lié à l'import,
    donc surcharger `settings` en cours de test serait sans effet — et on
    perdrait la garantie que la protection existe.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_user(db):
    return User.objects.create_user(
        username="broker-owner",
        email="owner@leotrade.test",
        password=PASSWORD,
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="broker-intruder",
        email="intruder@leotrade.test",
        password=PASSWORD,
    )


@pytest.fixture
def client(api_user):
    c = APIClient()
    c.force_authenticate(user=api_user)
    return c


@pytest.fixture
def anonymous():
    return APIClient()


@pytest.fixture
def kyc_approved(db, api_user):
    from dashboard.models import KYCProfile

    return KYCProfile.objects.create(user=api_user, status="APPROVED")


@pytest.fixture
def deriv_account(db, api_user):
    account = BrokerAccount.objects.create(
        user=api_user,
        name="Deriv principal",
        broker="DERIV",
        mode="PAPER",
        deriv_app_id="1089",
        deriv_currency="USD",
        is_active=True,
        status="ACTIVE",
    )
    account.set_secret("DERIV_TOKEN", SECRET_VALUES["deriv_token"])
    return account


def _list_url():
    return reverse("api-brokers-list")


def _detail_url(pk):
    return reverse("api-brokers-detail", kwargs={"pk": pk})


def _action_url(pk, name):
    return reverse(f"api-brokers-{name}", kwargs={"pk": pk})


def _assert_no_secret_leak(payload):
    """Aucune valeur sentinelle ne doit apparaître nulle part dans la réponse."""
    blob = str(payload)
    for field, value in SECRET_VALUES.items():
        assert value not in blob, f"Fuite du secret « {field} » dans la réponse."


# ─────────────────────────────────────────────────────────────────────────────
#  1. Non-divulgation des secrets — la propriété la plus importante
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSecretsNeverLeak:

    def test_list_never_returns_secret_values(self, client, deriv_account):
        response = client.get(_list_url())

        assert response.status_code == 200
        _assert_no_secret_leak(response.json())

    def test_detail_never_returns_secret_values(self, client, deriv_account):
        response = client.get(_detail_url(deriv_account.pk))

        assert response.status_code == 200
        _assert_no_secret_leak(response.json())

    def test_create_response_never_echoes_the_submitted_secret(self, client):
        response = client.post(_list_url(), {
            "name": "Binance spot",
            "broker": "BINANCE",
            "mode": "PAPER",
            "api_key": SECRET_VALUES["api_key"],
            "api_secret": SECRET_VALUES["api_secret"],
        }, format="json")

        assert response.status_code == 201, response.json()
        _assert_no_secret_leak(response.json())

    def test_update_response_never_echoes_the_submitted_secret(self, client, deriv_account):
        response = client.patch(_detail_url(deriv_account.pk), {
            "deriv_token": "a1-ROTATED-999",
        }, format="json")

        assert response.status_code == 200, response.json()
        assert "a1-ROTATED-999" not in str(response.json())

    def test_detail_exposes_secret_presence_without_the_value(self, client, deriv_account):
        body = client.get(_detail_url(deriv_account.pk)).json()

        assert body["secrets"]["deriv_token"]["configured"] is True
        assert body["secrets"]["api_key"]["configured"] is False
        # La métadonnée ne doit porter que des dates, jamais de valeur.
        assert set(body["secrets"]["deriv_token"]) == {
            "configured", "updated_at", "rotated_at",
        }

    def test_schema_does_not_expose_secrets_as_readable(self, client):
        """Le contrat OpenAPI lui-même ne doit pas annoncer ces champs en lecture."""
        from api.serializers.brokers import BrokerAccountSerializer

        serializer = BrokerAccountSerializer()
        for field in SECRET_VALUES:
            assert serializer.fields[field].write_only is True, (
                f"Le champ « {field} » n'est pas write_only : il sortira en lecture."
            )


# ─────────────────────────────────────────────────────────────────────────────
#  2. Les secrets soumis sont réellement chiffrés et conservés
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSecretPersistence:

    def test_submitted_secret_is_stored_encrypted(self, client):
        response = client.post(_list_url(), {
            "name": "Binance spot",
            "broker": "BINANCE",
            "mode": "PAPER",
            "api_key": SECRET_VALUES["api_key"],
            "api_secret": SECRET_VALUES["api_secret"],
        }, format="json")

        account = BrokerAccount.objects.get(pk=response.json()["id"])
        credential = BrokerCredential.objects.get(
            broker_account=account, secret_type="API_KEY",
        )

        # Chiffré au repos…
        assert SECRET_VALUES["api_key"] not in credential.secret_value_encrypted
        # …mais déchiffrable côté serveur pour l'appel broker.
        assert account.api_key == SECRET_VALUES["api_key"]

    def test_empty_secret_preserves_the_existing_one(self, client, deriv_account):
        """Modifier un compte sans ressaisir ses clés ne doit pas les effacer."""
        client.patch(_detail_url(deriv_account.pk), {
            "name": "Deriv renommé",
            "deriv_token": "",
        }, format="json")

        deriv_account.refresh_from_db()
        assert deriv_account.name == "Deriv renommé"
        assert deriv_account.deriv_token == SECRET_VALUES["deriv_token"]

    def test_omitted_secret_preserves_the_existing_one(self, client, deriv_account):
        client.patch(_detail_url(deriv_account.pk), {"name": "Deriv v2"}, format="json")

        deriv_account.refresh_from_db()
        assert deriv_account.deriv_token == SECRET_VALUES["deriv_token"]

    def test_rotating_a_secret_replaces_the_previous_value(self, client, deriv_account):
        client.patch(_detail_url(deriv_account.pk), {
            "deriv_token": "a1-ROTATED-999",
        }, format="json")

        deriv_account.refresh_from_db()
        assert deriv_account.deriv_token == "a1-ROTATED-999"

    def test_missing_secrets_are_reported_to_the_client(self, client):
        """L'interface doit savoir quoi demander sans deviner."""
        response = client.post(_list_url(), {
            "name": "Binance sans clés",
            "broker": "BINANCE",
            "mode": "PAPER",
        }, format="json")

        body = response.json()
        assert response.status_code == 201
        assert sorted(body["missing_secrets"]) == ["api_key", "api_secret"]
        assert body["is_ready_to_connect"] is False


# ─────────────────────────────────────────────────────────────────────────────
#  3. Garde KYC sur le mode LIVE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLiveModeRequiresKyc:

    def test_creating_a_live_account_is_denied_without_approved_kyc(self, client):
        response = client.post(_list_url(), {
            "name": "Deriv LIVE",
            "broker": "DERIV",
            "mode": "LIVE",
            "deriv_app_id": "1089",
            "deriv_currency": "USD",
        }, format="json")

        assert response.status_code == 403
        assert response.json()["code"] == "KYC_REQUIRED"
        assert not BrokerAccount.objects.filter(mode="LIVE").exists()

    def test_switching_an_account_to_live_is_denied_without_approved_kyc(
        self, client, deriv_account,
    ):
        response = client.patch(_detail_url(deriv_account.pk), {
            "mode": "LIVE",
        }, format="json")

        assert response.status_code == 403
        deriv_account.refresh_from_db()
        assert deriv_account.mode == "PAPER"

    def test_pending_kyc_is_not_enough(self, client, api_user):
        from dashboard.models import KYCProfile

        KYCProfile.objects.create(user=api_user, status="UNDER_REVIEW")

        response = client.post(_list_url(), {
            "name": "Deriv LIVE",
            "broker": "DERIV",
            "mode": "LIVE",
            "deriv_app_id": "1089",
            "deriv_currency": "USD",
        }, format="json")

        assert response.status_code == 403

    def test_approved_kyc_unlocks_live(self, client, kyc_approved):
        response = client.post(_list_url(), {
            "name": "Deriv LIVE",
            "broker": "DERIV",
            "mode": "LIVE",
            "deriv_app_id": "1089",
            "deriv_currency": "USD",
        }, format="json")

        assert response.status_code == 201, response.json()
        assert response.json()["mode"] == "LIVE"

    def test_paper_mode_never_requires_kyc(self, client):
        response = client.post(_list_url(), {
            "name": "Deriv PAPER",
            "broker": "DERIV",
            "mode": "PAPER",
            "deriv_app_id": "1089",
            "deriv_currency": "USD",
        }, format="json")

        assert response.status_code == 201

    def test_returning_to_paper_is_always_allowed(self, client, api_user):
        """Un compte LIVE existant doit pouvoir repasser en PAPER sans KYC :
        on ne verrouille jamais la porte de sortie."""
        account = BrokerAccount.objects.create(
            user=api_user, name="Legacy LIVE", broker="DERIV", mode="LIVE",
            deriv_app_id="1089", deriv_currency="USD", is_active=True,
        )

        response = client.patch(_detail_url(account.pk), {"mode": "PAPER"}, format="json")

        assert response.status_code == 200
        account.refresh_from_db()
        assert account.mode == "PAPER"


# ─────────────────────────────────────────────────────────────────────────────
#  4. Cloisonnement et authentification
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTenantIsolation:

    def test_anonymous_access_is_rejected_not_crashed(self, anonymous):
        """Sans authentification, on attend un 401 — pas un 500 provoqué par
        un filtre sur AnonymousUser."""
        response = anonymous.get(_list_url())

        assert response.status_code in (401, 403), response.status_code

    def test_another_users_account_is_invisible(self, client, other_user):
        BrokerAccount.objects.create(
            user=other_user, name="Compte voisin", broker="BINANCE", mode="PAPER",
        )

        body = client.get(_list_url()).json()

        assert body["count"] == 0

    def test_another_users_account_cannot_be_read(self, client, other_user):
        foreign = BrokerAccount.objects.create(
            user=other_user, name="Compte voisin", broker="BINANCE", mode="PAPER",
        )

        assert client.get(_detail_url(foreign.pk)).status_code == 404

    def test_another_users_account_cannot_be_modified(self, client, other_user):
        foreign = BrokerAccount.objects.create(
            user=other_user, name="Compte voisin", broker="BINANCE", mode="PAPER",
        )

        response = client.patch(_detail_url(foreign.pk), {"name": "Détourné"}, format="json")

        assert response.status_code == 404
        foreign.refresh_from_db()
        assert foreign.name == "Compte voisin"

    def test_creation_cannot_be_attributed_to_another_user(self, client, api_user, other_user):
        """Un `user` dans le corps de requête ne doit pas être honoré."""
        response = client.post(_list_url(), {
            "name": "Tentative",
            "broker": "BINANCE",
            "mode": "PAPER",
            "user": other_user.pk,
        }, format="json")

        assert response.status_code == 201
        assert BrokerAccount.objects.get(pk=response.json()["id"]).user_id == api_user.pk


# ─────────────────────────────────────────────────────────────────────────────
#  5. Validation par broker
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPerBrokerValidation:

    def test_mt5_requires_login_and_server(self, client):
        response = client.post(_list_url(), {
            "name": "MT5 incomplet",
            "broker": "MT5",
            "mode": "PAPER",
        }, format="json")

        assert response.status_code == 400
        body = response.json()
        assert "login" in body and "server" in body

    def test_deriv_requires_app_id(self, client):
        response = client.post(_list_url(), {
            "name": "Deriv incomplet",
            "broker": "DERIV",
            "mode": "PAPER",
            "deriv_currency": "USD",
        }, format="json")

        assert response.status_code == 400
        assert "deriv_app_id" in response.json()

    def test_duplicate_name_is_a_field_error_not_a_crash(self, client, deriv_account):
        response = client.post(_list_url(), {
            "name": deriv_account.name,
            "broker": "BINANCE",
            "mode": "PAPER",
        }, format="json")

        assert response.status_code == 400
        assert "name" in response.json()

    def test_the_same_name_is_free_for_another_user(self, other_user, deriv_account):
        intruder = APIClient()
        intruder.force_authenticate(user=other_user)

        response = intruder.post(_list_url(), {
            "name": deriv_account.name,
            "broker": "BINANCE",
            "mode": "PAPER",
        }, format="json")

        assert response.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
#  6. Compte par défaut
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDefaultAccount:

    def test_set_default_promotes_exactly_one_account(self, client, api_user):
        first = BrokerAccount.objects.create(
            user=api_user, name="A", broker="BINANCE", mode="PAPER", is_default=True,
        )
        second = BrokerAccount.objects.create(
            user=api_user, name="B", broker="BINANCE", mode="PAPER",
        )

        response = client.post(_action_url(second.pk, "set-default"))

        assert response.status_code == 200
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.is_default is True
        assert first.is_default is False
        assert BrokerAccount.objects.filter(user=api_user, is_default=True).count() == 1

    def test_creating_a_default_account_demotes_the_previous_one(self, client, api_user):
        first = BrokerAccount.objects.create(
            user=api_user, name="A", broker="BINANCE", mode="PAPER", is_default=True,
        )

        response = client.post(_list_url(), {
            "name": "B", "broker": "BINANCE", "mode": "PAPER", "is_default": True,
        }, format="json")

        assert response.status_code == 201, response.json()
        first.refresh_from_db()
        assert first.is_default is False

    def test_set_default_on_another_users_account_is_refused(self, client, other_user):
        foreign = BrokerAccount.objects.create(
            user=other_user, name="Voisin", broker="BINANCE", mode="PAPER",
        )

        assert client.post(_action_url(foreign.pk, "set-default")).status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  7. Test de connexion
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestConnectionTest:

    def test_missing_secrets_block_the_call_before_any_network_io(self, client, api_user, monkeypatch):
        account = BrokerAccount.objects.create(
            user=api_user, name="Binance sans clés", broker="BINANCE", mode="PAPER",
        )

        called = []
        monkeypatch.setattr(
            "brokers.services_connection.BrokerConnectionService.test_connection",
            lambda acc: called.append(acc) or {"success": True, "payload": {}},
        )

        response = client.post(_action_url(account.pk, "test-connection"))

        assert response.status_code == 409
        assert response.json()["code"] == "MISSING_SECRETS"
        assert sorted(response.json()["missing_secrets"]) == ["api_key", "api_secret"]
        assert called == [], "Un appel broker a été émis malgré des identifiants incomplets."

    def test_successful_connection_persists_the_state(self, client, deriv_account, monkeypatch):
        monkeypatch.setattr(
            "brokers.services_connection.BrokerConnectionService.test_connection",
            lambda acc: {"success": True, "payload": {"balance": "100.00"}},
        )

        response = client.post(_action_url(deriv_account.pk, "test-connection"))

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        _assert_no_secret_leak(response.json())

    def test_failed_connection_returns_the_reason(self, client, deriv_account, monkeypatch):
        monkeypatch.setattr(
            "brokers.services_connection.BrokerConnectionService.test_connection",
            lambda acc: {"success": False, "error": "token expiré"},
        )

        response = client.post(_action_url(deriv_account.pk, "test-connection"))

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "CONNECTION_FAILED"
        assert "token expiré" in body["detail"]

    def test_connection_failure_notifies_the_owner(self, client, deriv_account, monkeypatch):
        monkeypatch.setattr(
            "brokers.services_connection.BrokerConnectionService.test_connection",
            lambda acc: {"success": False, "error": "token expiré"},
        )

        client.post(_action_url(deriv_account.pk, "test-connection"))

        from notifications.models import Notification
        assert Notification.objects.filter(
            user=deriv_account.user, event_type="BROKER_CONNECTION_FAILED",
        ).exists()

    def test_a_failing_notification_never_breaks_the_call(self, client, deriv_account, monkeypatch):
        """Règle permanente : une notification qui échoue ne bloque jamais
        l'action métier qu'elle accompagne."""
        monkeypatch.setattr(
            "brokers.services_connection.BrokerConnectionService.test_connection",
            lambda acc: {"success": True, "payload": {}},
        )
        monkeypatch.setattr(
            "notifications.services.NotificationService.notify",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bus indisponible")),
        )

        response = client.post(_action_url(deriv_account.pk, "test-connection"))

        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  8. Suppression protégée
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProtectedDeletion:

    def test_an_unused_account_can_be_deleted(self, client, api_user):
        account = BrokerAccount.objects.create(
            user=api_user, name="Jamais utilisé", broker="BINANCE", mode="PAPER",
        )

        assert client.delete(_detail_url(account.pk)).status_code == 204
        assert not BrokerAccount.objects.filter(pk=account.pk).exists()

    def test_an_account_with_a_portfolio_cannot_be_deleted(self, client, api_user, deriv_account):
        """CASCADE effacerait l'historique du portefeuille : on refuse."""
        from portfolio.models import Portfolio

        Portfolio.objects.create(
            user=api_user, broker_account=deriv_account, name="P1",
            starting_balance=Decimal("1000.00"), current_balance=Decimal("1000.00"),
            available_cash=Decimal("1000.00"), equity=Decimal("1000.00"),
            max_equity=Decimal("1000.00"), is_active=True,
        )

        response = client.delete(_detail_url(deriv_account.pk))

        assert response.status_code == 409
        assert response.json()["code"] == "LINKED_PORTFOLIOS"
        assert BrokerAccount.objects.filter(pk=deriv_account.pk).exists()


# ─────────────────────────────────────────────────────────────────────────────
#  9. Santé du parc
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHealth:

    def test_health_reports_each_account(self, client, deriv_account):
        response = client.get(reverse("api-brokers-health"))

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        row = body["results"][0]
        assert row["id"] == deriv_account.pk
        assert row["circuit_state"] in {"CLOSED", "OPEN", "HALF_OPEN", "UNAVAILABLE"}

    def test_health_never_leaks_secrets(self, client, deriv_account):
        _assert_no_secret_leak(client.get(reverse("api-brokers-health")).json())

    def test_health_is_empty_without_accounts_not_an_error(self, client):
        """Zéro broker est un état légitime, pas une erreur : l'interface doit
        pouvoir afficher un état vide explicite."""
        response = client.get(reverse("api-brokers-health"))

        assert response.status_code == 200
        assert response.json() == {"results": [], "count": 0}

    def test_health_only_covers_the_callers_accounts(self, client, other_user):
        BrokerAccount.objects.create(
            user=other_user, name="Voisin", broker="BINANCE", mode="PAPER",
        )

        assert client.get(reverse("api-brokers-health")).json()["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
#  10. Contraintes d'instrument
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestConstraints:

    @pytest.fixture
    def constraint(self, db):
        from brokers.models import BrokerConstraint

        return BrokerConstraint.objects.create(
            broker="DERIV", symbol="R_75",
            min_qty=Decimal("0.1"), max_qty=Decimal("100"),
            qty_step=Decimal("0.01"), min_notional=Decimal("1.00"),
            raw_payload={"internal": "ne doit pas sortir"},
        )

    def test_raw_broker_payload_is_not_exposed(self, client, deriv_account, constraint):
        """`raw_payload` est la réponse brute du broker, de forme non garantie :
        elle n'a pas à traverser le contrat d'API publique."""
        body = client.get(reverse("api-broker-constraints-list")).json()

        assert body["count"] == 1
        assert "raw_payload" not in body["results"][0]
        assert "ne doit pas sortir" not in str(body)

    def test_constraints_are_scoped_to_the_users_brokers(self, client, constraint):
        """Sans compte DERIV, l'utilisateur ne voit pas les contraintes DERIV."""
        assert client.get(reverse("api-broker-constraints-list")).json()["count"] == 0

    def test_sync_requires_a_symbol(self, client, deriv_account):
        response = client.post(_action_url(deriv_account.pk, "sync-constraint"), {}, format="json")

        assert response.status_code == 400
        assert "symbol" in response.json()

    def test_sync_upstream_failure_is_a_gateway_error(self, client, deriv_account, monkeypatch):
        """Un broker injoignable n'est pas une erreur du client : 502, pas 500."""
        monkeypatch.setattr(
            "brokers.services.base.BrokerConstraintSyncService.sync_symbol_constraint",
            lambda acc, sym: (_ for _ in ()).throw(RuntimeError("broker injoignable")),
        )

        response = client.post(
            _action_url(deriv_account.pk, "sync-constraint"),
            {"symbol": "R_75"}, format="json",
        )

        assert response.status_code == 502
        assert response.json()["code"] == "SYNC_FAILED"


# ─────────────────────────────────────────────────────────────────────────────
#  11. Un message d'erreur broker ne doit pas devenir un canal de fuite
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestErrorRedaction:
    """Certains brokers renvoient la valeur soumise dans leur message d'erreur.

    Ce message est persisté dans `last_connection_error` puis servi par
    l'API : c'est le chemin par lequel un secret ressortirait sans qu'on
    le remarque.
    """

    def test_a_broker_error_echoing_the_token_is_redacted_before_storage(
        self, client, deriv_account, monkeypatch,
    ):
        leaky = f"Invalid token: {SECRET_VALUES['deriv_token']} — rejected"
        monkeypatch.setattr(
            "infrastructure.broker_clients.BrokerClientFactory.build",
            lambda acc: type("C", (), {
                "test_connection": staticmethod(
                    lambda: (_ for _ in ()).throw(RuntimeError(leaky))
                ),
            })(),
        )

        response = client.post(_action_url(deriv_account.pk, "test-connection"))

        assert response.status_code == 400
        _assert_no_secret_leak(response.json())

        deriv_account.refresh_from_db()
        assert SECRET_VALUES["deriv_token"] not in (deriv_account.last_connection_error or "")
        assert "«secret masqué»" in deriv_account.last_connection_error

    def test_redaction_keeps_the_useful_part_of_the_message(self, deriv_account):
        """Masquer ne doit pas rendre le diagnostic inutilisable."""
        from brokers.services_accounts import BrokerAccountService

        cleaned = BrokerAccountService.redact_secrets(
            deriv_account,
            f"401 Unauthorized: token {SECRET_VALUES['deriv_token']} expired",
        )

        assert "401 Unauthorized" in cleaned
        assert "expired" in cleaned
        assert SECRET_VALUES["deriv_token"] not in cleaned

    def test_an_error_without_any_secret_is_left_intact(self, deriv_account):
        from brokers.services_accounts import BrokerAccountService

        original = "Connexion refusée par le serveur (timeout après 30s)"
        assert BrokerAccountService.redact_secrets(deriv_account, original) == original
