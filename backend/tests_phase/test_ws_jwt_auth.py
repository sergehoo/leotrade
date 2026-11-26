"""
tests_phase/test_ws_jwt_auth.py
===============================

Authentification JWT des WebSockets.

`AuthMiddlewareStack` ne lit qu'un cookie de session. React et Flutter
portent un JWT en mémoire et n'ont pas de cookie : toutes leurs
connexions temps réel — streaming de l'assistant, notifications,
exécution — étaient fermées en 4401.

Le jeton passe par le sous-protocole et non par la chaîne de requête :
un `?token=` survit dans les journaux d'accès du serveur, des proxies et
des CDN bien au-delà de ses 15 minutes de validité.

Les tests pilotent le code asynchrone via `async_to_sync` plutôt que
d'ajouter `pytest-asyncio` au projet. `transaction=True` est nécessaire :
les accès base passent par un fil d'exécution séparé, qui ne verrait pas
une transaction de test non committée.
"""

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from core.ws_auth import JWT_SUBPROTOCOL, JWTAuthMiddlewareStack

User = get_user_model()


def _scope(protocols=None, query_string: bytes = b"", via: str = "asgi") -> dict:
    """Construit un scope WebSocket.

    `via="asgi"` reproduit ce que fournissent Daphne et Uvicorn :
    `scope["subprotocols"]` déjà découpé. `via="header"` reproduit un
    serveur qui ne renseigne pas la clé et laisse l'en-tête brut.
    """
    scope = {"type": "websocket", "headers": [], "query_string": query_string}
    if protocols is None:
        return scope
    if via == "asgi":
        scope["subprotocols"] = list(protocols)
    else:
        scope["headers"] = [
            (b"sec-websocket-protocol", ", ".join(protocols).encode("latin-1"))
        ]
    return scope


class _Recorder:
    """Point d'arrivée qui mémorise le scope reçu."""

    def __init__(self):
        self.scope = None

    async def __call__(self, scope, receive, send):
        self.scope = scope


def _resolve(protocols=None, query_string: bytes = b"", via: str = "asgi") -> dict:
    """Résout un scope à travers la MÊME composition qu'en production.

    Tester `JWTAuthMiddleware` seul masquerait le défaut qui a réellement
    existé : la pile session, exécutée ensuite, écrasait `scope["user"]`.
    """
    recorder = _Recorder()

    async def run():
        await JWTAuthMiddlewareStack(recorder)(
            _scope(protocols, query_string, via), None, None,
        )

    async_to_sync(run)()
    return recorder.scope


@pytest.fixture
def ws_user(transactional_db):
    return User.objects.create_user(
        username="ws", email="ws@leotrade.test", password="StrongPass123!",
    )


def _token_for(user) -> str:
    return str(RefreshToken.for_user(user).access_token)


# ─────────────────────────────────────────────────────────────────────────────
#  1. Le middleware
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTSubprotocolAuth:

    def test_a_valid_token_authenticates_the_connection(self, ws_user):
        scope = _resolve([JWT_SUBPROTOCOL, _token_for(ws_user)])

        assert scope["user"].is_authenticated
        assert scope["user"].pk == ws_user.pk
        # Mémorisé pour que le consumer l'écho : sans écho, un navigateur
        # ferme la connexion qu'il vient d'ouvrir.
        assert scope["ws_subprotocol"] == JWT_SUBPROTOCOL

    def test_a_token_is_also_read_from_the_raw_header(self, ws_user):
        """Repli pour les serveurs ASGI qui ne renseignent pas
        `scope["subprotocols"]`."""
        scope = _resolve([JWT_SUBPROTOCOL, _token_for(ws_user)], via="header")

        assert scope["user"].is_authenticated

    def test_a_forged_token_yields_an_anonymous_user(self, ws_user):
        scope = _resolve([JWT_SUBPROTOCOL, "ceci.nest.pas.un.jeton"])

        assert not scope["user"].is_authenticated

    def test_an_announced_but_empty_token_is_not_silently_ignored(self, ws_user):
        """Annoncer le sous-protocole sans jeton est une tentative
        d'authentification, pas son absence."""
        scope = _resolve([JWT_SUBPROTOCOL])

        assert not scope["user"].is_authenticated
        assert scope["ws_subprotocol"] == JWT_SUBPROTOCOL

    def test_an_invalid_token_does_not_fall_back_to_the_session(self, ws_user):
        """Retomber sur la session masquerait une authentification JWT
        échouée derrière une autre, et rendrait le diagnostic impossible."""
        scope = _resolve([JWT_SUBPROTOCOL, "jeton.invalide"])

        assert "user" in scope
        assert not scope["user"].is_authenticated

    def test_without_the_marker_the_session_path_is_left_untouched(self, transactional_db):
        """Les écrans Django historiques n'annoncent aucun sous-protocole :
        le middleware doit les laisser passer à l'authentification session."""
        scope = _resolve(None)

        assert scope.get("ws_subprotocol") is None
        # La pile session a bien été traversée : elle pose un `user`
        # paresseux, anonyme faute de cookie.
        assert "user" in scope
        assert not scope["user"].is_authenticated

    def test_a_token_in_the_query_string_is_never_honoured(self, ws_user):
        """Garde explicite : un jeton en query string figure dans les
        journaux d'accès du serveur, des proxies et des CDN."""
        scope = _resolve(None, query_string=f"token={_token_for(ws_user)}".encode())

        assert not scope["user"].is_authenticated


# ─────────────────────────────────────────────────────────────────────────────
#  2. Bout en bout sur le consumer de Leo
# ─────────────────────────────────────────────────────────────────────────────

class TestAssistantWebSocket:

    def _connect(self, protocols):
        """Cible la pile d'authentification, pas le validateur d'origine.

        `AllowedHostsOriginValidator` refuse le communicateur de test faute
        d'en-tête Origin, et fermerait en 1000 avant d'atteindre le
        consumer. On monte donc le routeur sous le seul middleware
        concerné : c'est lui que ces tests vérifient.
        """
        import ai_assistant.routing
        from channels.routing import URLRouter

        from core.ws_auth import JWTAuthMiddlewareStack

        application = JWTAuthMiddlewareStack(
            URLRouter(ai_assistant.routing.websocket_urlpatterns)
        )

        async def run():
            communicator = WebsocketCommunicator(
                application, "/ws/assistant/chat/", subprotocols=protocols,
            )
            result = await communicator.connect(timeout=10)
            await communicator.disconnect()
            return result

        return async_to_sync(run)()

    def test_a_jwt_client_is_accepted_and_the_subprotocol_echoed(self, ws_user):
        connected, subprotocol = self._connect(
            [JWT_SUBPROTOCOL, _token_for(ws_user)]
        )

        assert connected, "Le client JWT doit être accepté."
        assert subprotocol == JWT_SUBPROTOCOL, (
            "Sans écho du sous-protocole, un navigateur ferme la connexion."
        )

    def test_an_anonymous_client_is_refused(self, transactional_db):
        connected, code = self._connect(None)

        assert not connected
        assert code == 4401

    def test_a_client_with_an_invalid_token_is_refused(self, transactional_db):
        connected, code = self._connect([JWT_SUBPROTOCOL, "jeton.invalide"])

        assert not connected
        assert code == 4401


# ─────────────────────────────────────────────────────────────────────────────
#  Validation d'origine : les clients natifs n'envoient pas d'en-tête Origin
# ─────────────────────────────────────────────────────────────────────────────

def _handshake(scope):
    """Déroule une poignée de main et rapporte ce que le serveur a répondu.

    Le refus passe par `WebsocketDenier`, un consumer : il faut donc lui
    fournir un flux `receive` qui se termine, sinon la boucle du consumer
    ne rend jamais la main.
    """
    from core.ws_auth import JWTFriendlyOriginValidator

    recorder = _Recorder()
    validator = JWTFriendlyOriginValidator(recorder)

    incoming = [
        {"type": "websocket.connect"},
        {"type": "websocket.disconnect", "code": 1000},
    ]
    sent = []

    async def receive():
        return incoming.pop(0) if incoming else {
            "type": "websocket.disconnect", "code": 1000,
        }

    async def send(message):
        sent.append(message)

    async_to_sync(validator)(scope, receive, send)
    return recorder, sent


@pytest.mark.django_db(transaction=True)
class TestOriginValidation:
    """`AllowedHostsOriginValidator` refusait toute connexion sans `Origin`.

    Un navigateur en envoie toujours un ; Dart, Swift et Kotlin, jamais.
    La socket de Leo était donc refusée en 403 sur mobile avant même
    d'atteindre l'authentification — et aucune reconnexion n'y changeait
    rien.

    Les tests ci-dessus montent `JWTAuthMiddlewareStack` seul, sans le
    validateur qui l'enveloppe dans `asgi.py` : le défaut vivait entre les
    deux, et ne s'est vu qu'en faisant tourner l'application sur un
    téléphone.
    """

    def test_a_native_client_with_a_token_is_let_through(self):
        """Pas d'Origine, mais un jeton : c'est une application native."""
        recorder, _ = _handshake(_scope(protocols=[JWT_SUBPROTOCOL, "jeton"]))

        assert recorder.scope is not None, "la connexion aurait dû passer"

    def test_a_cookie_client_without_origin_is_still_refused(self):
        """Sans jeton, rien ne change : l'origine reste exigée.

        C'est ce cas que la vérification protège — le navigateur joint le
        cookie de session d'office, et c'est ce qui rend le détournement
        possible depuis une page tierce.
        """
        recorder, sent = _handshake(_scope())

        assert recorder.scope is None
        assert any(m.get("type") == "websocket.close" for m in sent)

    def test_a_foreign_origin_is_refused_even_with_a_token(self):
        """Un jeton ne dispense pas de la vérification quand l'origine existe."""
        scope = _scope(protocols=[JWT_SUBPROTOCOL, "jeton"])
        scope["headers"] = list(scope["headers"]) + [
            (b"origin", b"https://ailleurs.example"),
        ]

        recorder, sent = _handshake(scope)

        assert recorder.scope is None
        assert any(m.get("type") == "websocket.close" for m in sent)

    def test_an_allowed_origin_still_passes(self):
        """Le chemin navigateur n'est pas touché."""
        scope = _scope()
        scope["headers"] = list(scope["headers"]) + [
            (b"origin", b"http://localhost:8000"),
        ]

        recorder, _ = _handshake(scope)

        assert recorder.scope is not None
