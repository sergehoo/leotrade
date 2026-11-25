"""Context processors des templates Django (interface web historique).

Toute la logique vit dans `core.services_context` : les clients React et
Flutter consomment la même résolution via /api/v1/context/. Ce module ne fait
plus que l'adaptation au rendu de template.
"""

from core.services_context import (
    build_app_context,
    safe_default_portfolio,
)


def global_trading_context(request):
    if not request.user.is_authenticated:
        return {}

    context = build_app_context(request.user, session=request.session)

    # On garde la session alignée sur la vérité broker pour que la barre
    # latérale, rendue côté serveur, ne clignote pas au changement de mode.
    if request.session.get("trading_mode") != context["trading_mode"]:
        request.session["trading_mode"] = context["trading_mode"]

    return context


def portfolio_context(request):
    if not request.user.is_authenticated:
        return {}
    return {"default_portfolio": safe_default_portfolio(request.user)}
