"""
core/ws_auth.py
===============

Authentification JWT des connexions WebSocket.

`AuthMiddlewareStack` de Channels ne sait lire qu'un cookie de session.
Les clients React et Flutter portent un JWT en mémoire et n'ont pas de
cookie : leurs connexions étaient fermées en 4401, ce qui rendait tout le
temps réel — streaming de l'assistant, notifications, exécution —
inaccessible depuis les deux nouvelles surfaces.

Le jeton transite par le sous-protocole WebSocket, pas par la chaîne de
requête. Un `?token=` figure dans les journaux d'accès du serveur, des
proxies et des CDN, où il survit bien au-delà de ses 15 minutes de
validité. L'en-tête `Sec-WebSocket-Protocol`, lui, n'est pas journalisé,
et c'est le seul en-tête qu'un navigateur laisse définir à l'ouverture
d'un WebSocket.

    // Web
    new WebSocket(url, ["leotrade.jwt", accessToken])

    // Dart
    WebSocketChannel.connect(uri, protocols: ["leotrade.jwt", accessToken])

L'authentification par session reste active en repli : les écrans Django
historiques continuent de fonctionner sans modification.
"""

from __future__ import annotations

import logging

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

log = logging.getLogger("leotrade.ws.auth")

#: Marqueur annonçant qu'un jeton suit dans la liste des sous-protocoles.
JWT_SUBPROTOCOL = "leotrade.jwt"


@database_sync_to_async
def _user_from_token(raw_token: str):
    """Résout l'utilisateur porté par un jeton d'accès, ou l'anonyme.

    Toute erreur de validation donne un anonyme : la connexion sera
    refusée par le consumer. On ne distingue pas les causes — un jeton
    expiré, révoqué ou forgé ne doivent pas être discernables par le
    client.
    """
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

    authenticator = JWTAuthentication()
    try:
        validated = authenticator.get_validated_token(raw_token)
        return authenticator.get_user(validated)
    except (InvalidToken, TokenError, KeyError):
        return AnonymousUser()
    except Exception:
        log.exception("ws.token_validation_failed")
        return AnonymousUser()


def _extract_subprotocols(scope) -> list[str]:
    """Sous-protocoles annoncés par le client.

    La spécification ASGI les expose dans `scope["subprotocols"]`, déjà
    découpés par le serveur — c'est ce que fournissent Daphne et Uvicorn.
    Lire l'en-tête brut à la place renvoyait une liste vide et faisait
    retomber toutes les connexions JWT sur la pile session.

    L'en-tête reste lu en second, pour les serveurs ASGI qui ne
    renseignent pas la clé.
    """
    declared = scope.get("subprotocols")
    if declared:
        return [str(item).strip() for item in declared if str(item).strip()]

    for name, value in scope.get("headers") or []:
        if name == b"sec-websocket-protocol":
            decoded = value.decode("latin-1")
            return [item.strip() for item in decoded.split(",") if item.strip()]
    return []


class JWTAuthMiddleware:
    """Aiguille entre authentification JWT et authentification session.

    Les deux chemins mènent à la MÊME application ; ce qui change est le
    middleware traversé. La distinction est structurelle, pas cosmétique :
    `AuthMiddleware` de Channels écrase `scope["user"]` par un objet
    paresseux résolu depuis la session. Laisser la pile session s'exécuter
    après une authentification JWT réussie annule donc celle-ci — l'erreur
    exacte que ce code a produite avant d'être corrigée, et que le test
    de bout en bout a révélée.
    """

    def __init__(self, inner, session_stack=None):
        #: Application atteinte quand le JWT a authentifié l'utilisateur.
        self.inner = inner
        #: Pile session, pour les clients qui ne présentent pas de jeton.
        self.session_stack = session_stack if session_stack is not None else inner

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        protocols = _extract_subprotocols(scope)

        # Le sous-protocole accepté est mémorisé pour que le consumer
        # puisse le renvoyer : un navigateur ferme la connexion si le
        # serveur n'écho pas l'un des protocoles proposés.
        scope["ws_subprotocol"] = None

        if JWT_SUBPROTOCOL not in protocols:
            return await self.session_stack(scope, receive, send)

        scope["ws_subprotocol"] = JWT_SUBPROTOCOL
        index = protocols.index(JWT_SUBPROTOCOL)
        token = protocols[index + 1] if index + 1 < len(protocols) else ""

        user = await _user_from_token(token) if token else AnonymousUser()

        # Jeton annoncé mais invalide : on ne retombe PAS sur la session.
        # Le faire masquerait une authentification échouée derrière une
        # autre et rendrait le diagnostic impossible.
        scope["user"] = user if (user and user.is_authenticated) else AnonymousUser()
        return await self.inner(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """JWT d'abord, session en repli — pour les écrans Django existants."""
    return JWTAuthMiddleware(inner, session_stack=AuthMiddlewareStack(inner))
