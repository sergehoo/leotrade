"""
tests_phase/test_mode_toggle.py
================================

Couverture : vue dashboard.views.trading_mode_toggle

Garanties vérifiées :
  1. Basculer vers LIVE met à jour TOUS les BrokerAccount.mode en DB.
  2. Basculer vers PAPER met à jour TOUS les BrokerAccount.mode en DB.
  3. La session est mise à jour immédiatement (sidebar cohérent).
  4. Si aucun broker actif, la session est mise à jour mais un warning est émis
     et aucun BrokerAccount n'est modifié.
  5. Les comptes déjà au bon mode sont skippés sans erreur.
  6. Un mode invalide est normalisé en PAPER (fail-safe).
  7. Un utilisateur ne peut pas basculer les comptes d'un autre utilisateur.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from brokers.models import BrokerAccount

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post_toggle(client, mode):
    """POST vers trading_mode_toggle et retourne la réponse."""
    return client.post(
        reverse("trading_mode_toggle"),
        data={"mode": mode},
        follow=True,  # suit les redirections
    )


def _make_broker(user, name, mode="PAPER", broker="DERIV", is_active=True):
    return BrokerAccount.objects.create(
        user=user,
        broker=broker,
        name=name,
        mode=mode,
        is_active=is_active,
        status="ACTIVE",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def logged_client(db, user):
    """Client Django authentifié en tant que `user`."""
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def three_paper_brokers(db, user):
    """3 BrokerAccount en mode PAPER pour le même utilisateur."""
    return [
        _make_broker(user, f"Broker {i}", mode="PAPER")
        for i in range(3)
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  1. Bascule PAPER → LIVE : tous les comptes mis à jour
# ─────────────────────────────────────────────────────────────────────────────

class TestTogglePaperToLive:

    @pytest.mark.django_db
    def test_all_active_accounts_set_to_live(self, logged_client, user, three_paper_brokers):
        """Bascule LIVE : les 3 BrokerAccount doivent avoir mode='LIVE' en DB."""
        _post_toggle(logged_client, "LIVE")

        modes = list(
            BrokerAccount.objects.filter(user=user).values_list("mode", flat=True)
        )
        assert all(m == "LIVE" for m in modes), f"Modes en DB : {modes}"

    @pytest.mark.django_db
    def test_session_updated_to_live(self, logged_client, user, three_paper_brokers):
        """La session doit refléter le nouveau mode immédiatement."""
        _post_toggle(logged_client, "LIVE")

        assert logged_client.session.get("trading_mode") == "LIVE"

    @pytest.mark.django_db
    def test_success_message_contains_live(self, logged_client, user, three_paper_brokers):
        """Un message de succès doit mentionner LIVE."""
        response = _post_toggle(logged_client, "LIVE")

        messages = [str(m) for m in response.context["messages"]]
        assert any("LIVE" in m for m in messages), f"Messages : {messages}"


# ─────────────────────────────────────────────────────────────────────────────
#  2. Bascule LIVE → PAPER : tous les comptes mis à jour
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleLiveToPaper:

    @pytest.fixture
    def three_live_brokers(self, db, user):
        return [
            _make_broker(user, f"Broker {i}", mode="LIVE")
            for i in range(3)
        ]

    @pytest.mark.django_db
    def test_all_active_accounts_set_to_paper(
        self, logged_client, user, three_live_brokers
    ):
        """Bascule PAPER : les 3 BrokerAccount doivent avoir mode='PAPER' en DB."""
        _post_toggle(logged_client, "PAPER")

        modes = list(
            BrokerAccount.objects.filter(user=user).values_list("mode", flat=True)
        )
        assert all(m == "PAPER" for m in modes), f"Modes en DB : {modes}"

    @pytest.mark.django_db
    def test_session_updated_to_paper(self, logged_client, user, three_live_brokers):
        _post_toggle(logged_client, "PAPER")
        assert logged_client.session.get("trading_mode") == "PAPER"


# ─────────────────────────────────────────────────────────────────────────────
#  3. Aucun broker actif
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleNoBroker:

    @pytest.mark.django_db
    def test_no_broker_session_still_updated(self, logged_client, user):
        """Sans broker actif, la session doit quand même être mise à jour."""
        _post_toggle(logged_client, "LIVE")
        assert logged_client.session.get("trading_mode") == "LIVE"

    @pytest.mark.django_db
    def test_no_broker_warning_emitted(self, logged_client, user):
        """Sans broker actif, un message de warning doit être émis."""
        response = _post_toggle(logged_client, "LIVE")
        messages = [str(m) for m in response.context["messages"]]
        assert any(
            "broker" in m.lower() or "configuré" in m.lower() for m in messages
        ), f"Messages : {messages}"

    @pytest.mark.django_db
    def test_inactive_broker_not_updated(self, logged_client, user):
        """Un compte inactif ne doit PAS être mis à jour."""
        inactive = _make_broker(user, "Inactive", mode="PAPER", is_active=False)
        _post_toggle(logged_client, "LIVE")

        inactive.refresh_from_db()
        assert inactive.mode == "PAPER"  # inchangé


# ─────────────────────────────────────────────────────────────────────────────
#  4. Comptes déjà au bon mode (skip)
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleAlreadyCorrectMode:

    @pytest.mark.django_db
    def test_skip_already_live(self, logged_client, user):
        """Bascule LIVE sur un compte déjà LIVE → aucune erreur, inchangé."""
        broker = _make_broker(user, "Already LIVE", mode="LIVE")

        _post_toggle(logged_client, "LIVE")

        broker.refresh_from_db()
        assert broker.mode == "LIVE"

    @pytest.mark.django_db
    def test_partial_update_mixed_modes(self, logged_client, user):
        """2 comptes PAPER + 1 LIVE : après bascule LIVE, tous doivent être LIVE."""
        b1 = _make_broker(user, "Paper 1", mode="PAPER")
        b2 = _make_broker(user, "Paper 2", mode="PAPER")
        b3 = _make_broker(user, "Already Live", mode="LIVE")

        _post_toggle(logged_client, "LIVE")

        for b in [b1, b2, b3]:
            b.refresh_from_db()
            assert b.mode == "LIVE", f"{b.name} est encore en {b.mode}"


# ─────────────────────────────────────────────────────────────────────────────
#  5. Mode invalide normalisé en PAPER
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleInvalidMode:

    @pytest.mark.django_db
    def test_invalid_mode_defaults_to_paper(self, logged_client, user):
        """Un mode inconnu doit être normalisé en PAPER (fail-safe)."""
        broker = _make_broker(user, "Broker", mode="LIVE")

        _post_toggle(logged_client, "INVALID_MODE")

        broker.refresh_from_db()
        assert broker.mode == "PAPER"
        assert logged_client.session.get("trading_mode") == "PAPER"

    @pytest.mark.django_db
    def test_empty_mode_defaults_to_paper(self, logged_client, user):
        """Un mode vide doit être normalisé en PAPER."""
        broker = _make_broker(user, "Broker", mode="LIVE")

        _post_toggle(logged_client, "")

        broker.refresh_from_db()
        assert broker.mode == "PAPER"


# ─────────────────────────────────────────────────────────────────────────────
#  6. Isolation entre utilisateurs
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleUserIsolation:

    @pytest.mark.django_db
    def test_other_user_accounts_untouched(self, db, user):
        """La bascule d'un utilisateur ne doit PAS affecter les comptes d'autrui."""
        # Créer un second utilisateur avec son propre broker
        other_user = User.objects.create_user(
            username="otheruser", password="x"
        )
        other_broker = _make_broker(other_user, "Other Broker", mode="PAPER")

        # Broker de l'utilisateur principal
        my_broker = _make_broker(user, "My Broker", mode="PAPER")

        # L'utilisateur principal bascule en LIVE
        client = Client()
        client.force_login(user)
        _post_toggle(client, "LIVE")

        # Mon broker → LIVE
        my_broker.refresh_from_db()
        assert my_broker.mode == "LIVE"

        # Broker de l'autre → toujours PAPER
        other_broker.refresh_from_db()
        assert other_broker.mode == "PAPER", (
            f"Le broker d'un autre utilisateur a été modifié ! mode={other_broker.mode}"
        )
