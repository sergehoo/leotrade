from django.db.utils import ProgrammingError, OperationalError

from wallet.models import Wallet
from portfolio.models import Portfolio


def _safe_default_portfolio(user):
    if not user or not user.is_authenticated:
        return None

    try:
        return (
            Portfolio.objects
            .filter(user=user, is_default=True)
            .select_related("broker_account")
            .only(
                "id",
                "user_id",
                "broker_account_id",
                "name",
                "description",
                "base_currency",
                "is_default",
                "is_active",
                "broker_account__id",
                "broker_account__name",
                "broker_account__broker",
                "broker_account__mode",
            )
            .first()
        )
    except (ProgrammingError, OperationalError):
        return None


def _safe_wallet(user):
    if not user or not user.is_authenticated:
        return None

    try:
        return Wallet.objects.filter(user=user).first()
    except (ProgrammingError, OperationalError):
        return None


def _resolve_trading_mode(user, session, default_portfolio):
    """
    Source de vérité du mode de trading affiché dans l'UI.

    Priorité (du plus fiable au plus volatile) :
      1. Mode du broker_account du portfolio par défaut.
      2. Mode majoritaire des broker_accounts actifs de l'utilisateur.
      3. Valeur en session (fallback purement UI).
      4. "PAPER" par défaut.

    Cela évite la divergence "le sidebar dit LIVE mais le broker est en
    PAPER", qui est exactement ce qui s'est produit avec l'ordre #41.
    """
    # 1) Portfolio par défaut → broker_account
    if default_portfolio is not None:
        broker_account = getattr(default_portfolio, "broker_account", None)
        mode = getattr(broker_account, "mode", None) if broker_account else None
        if mode in ("PAPER", "LIVE"):
            return mode

    # 2) Vote majoritaire sur les broker_accounts actifs
    try:
        from brokers.models import BrokerAccount
        modes = list(
            BrokerAccount.objects
            .filter(user=user, is_active=True)
            .values_list("mode", flat=True)
        )
        if modes:
            # S'il y a au moins un LIVE actif, on remonte LIVE (signal
            # explicite que l'utilisateur trade en réel quelque part).
            if "LIVE" in modes:
                return "LIVE"
            return "PAPER"
    except (ProgrammingError, OperationalError):
        pass

    # 3) Fallback session
    session_mode = session.get("trading_mode") if session else None
    if session_mode in ("PAPER", "LIVE"):
        return session_mode

    # 4) Défaut sûr
    return "PAPER"


def global_trading_context(request):
    if not request.user.is_authenticated:
        return {}

    portfolio = _safe_default_portfolio(request.user)
    wallet = _safe_wallet(request.user)
    trading_mode = _resolve_trading_mode(
        user=request.user,
        session=request.session,
        default_portfolio=portfolio,
    )

    # On garde la session synchro avec la vérité broker pour que le
    # sidebar (rendu côté serveur) ne flashe pas au changement.
    if request.session.get("trading_mode") != trading_mode:
        request.session["trading_mode"] = trading_mode

    return {
        "portfolio": portfolio,
        "wallet": wallet,
        "trading_mode": trading_mode,
    }


def portfolio_context(request):
    if not request.user.is_authenticated:
        return {}

    default_portfolio = _safe_default_portfolio(request.user)

    return {
        "default_portfolio": default_portfolio,
    }