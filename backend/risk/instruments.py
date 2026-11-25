"""
Classification des instruments — socle de la politique « Capital Preservation First ».

Pourquoi ce module existe
-------------------------
Tous les instruments ne se valent pas du point de vue de la préservation du
capital. Deux propriétés orthogonales comptent :

  1. **Profil d'espérance** : un indice synthétique Deriv a un avantage maison
     intégré (espérance NÉGATIVE par construction) — le temps joue contre
     l'utilisateur. Un ETF ou une paire FX majeure a une espérance
     structurellement neutre : le temps ne travaille pas contre lui.
  2. **Volatilité** : la crypto n'est pas négative-EV, mais sa volatilité
     impose un dimensionnement plus prudent.

D'où trois niveaux (`InstrumentTier`), chacun porteur d'une politique de risque
propre. Le niveau par défaut de la plateforme est CORE.

⚠️ Point technique important
----------------------------
`Asset.asset_class` n'est PAS fiable pour identifier un synthétique Deriv : la
commande de seed les enregistre avec `asset_class="INDEX"`, exactement comme un
vrai indice boursier. La classification s'appuie donc d'abord sur le **motif de
symbole** puis sur l'**exchange**, et seulement ensuite sur `asset_class`.

Un instrument non reconnu est classé SPECULATIVE (le plus restrictif) : en
préservation du capital, l'inconnu se traite comme dangereux, jamais comme sûr.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


class InstrumentTier:
    """Niveaux d'éligibilité, du plus sûr au plus dangereux."""

    CORE = "CORE"                # espérance non-négative, volatilité modérée
    VOLATILE = "VOLATILE"        # espérance non-négative, volatilité élevée
    SPECULATIVE = "SPECULATIVE"  # espérance NÉGATIVE par construction

    CHOICES = [
        (CORE, "Core — éligible préservation"),
        (VOLATILE, "Volatile — opt-in, volatilité élevée"),
        (SPECULATIVE, "Spéculatif — opt-in explicite, espérance négative"),
    ]
    ALL = (CORE, VOLATILE, SPECULATIVE)


@dataclass(frozen=True)
class TierPolicy:
    """Politique de risque attachée à un niveau d'instrument.

    Les plafonds sont des **maxima durs** : ils ne peuvent qu'abaisser le
    `max_risk_per_trade` du profil utilisateur, jamais l'augmenter.
    """

    tier: str
    label: str
    # Plafond dur du risque par trade, en % de l'équité.
    max_risk_per_trade_pct: Decimal
    # Exposition maximale sur un seul symbole, en % de l'équité.
    max_symbol_exposure_pct: Decimal
    # Exposition maximale cumulée du niveau, en % de l'équité.
    max_tier_exposure_pct: Decimal
    # Éligible au mode « préservation du capital » ?
    eligible_for_preservation: bool
    # Nécessite un opt-in explicite et tracé de l'utilisateur ?
    requires_explicit_optin: bool
    # Message de transparence affiché à l'utilisateur (jamais de promesse).
    disclosure: str


POLICIES: dict[str, TierPolicy] = {
    InstrumentTier.CORE: TierPolicy(
        tier=InstrumentTier.CORE,
        label="Core",
        max_risk_per_trade_pct=Decimal("0.50"),
        max_symbol_exposure_pct=Decimal("15.00"),
        max_tier_exposure_pct=Decimal("100.00"),
        eligible_for_preservation=True,
        requires_explicit_optin=False,
        disclosure=(
            "Instrument à espérance structurellement neutre. Le risque de perte "
            "reste réel : aucune performance n'est garantie."
        ),
    ),
    InstrumentTier.VOLATILE: TierPolicy(
        tier=InstrumentTier.VOLATILE,
        label="Volatile",
        max_risk_per_trade_pct=Decimal("0.25"),
        max_symbol_exposure_pct=Decimal("10.00"),
        max_tier_exposure_pct=Decimal("30.00"),
        eligible_for_preservation=False,
        requires_explicit_optin=True,
        disclosure=(
            "Instrument à volatilité élevée. Les variations peuvent être brutales "
            "et les pertes rapides. Exclu du mode préservation du capital."
        ),
    ),
    InstrumentTier.SPECULATIVE: TierPolicy(
        tier=InstrumentTier.SPECULATIVE,
        label="Spéculatif",
        max_risk_per_trade_pct=Decimal("0.25"),
        max_symbol_exposure_pct=Decimal("5.00"),
        max_tier_exposure_pct=Decimal("10.00"),
        eligible_for_preservation=False,
        requires_explicit_optin=True,
        disclosure=(
            "⚠ Instrument à espérance NÉGATIVE par construction (avantage maison "
            "intégré) : sur la durée, la probabilité mathématique joue contre "
            "l'utilisateur. Aucun système, y compris assisté par IA, ne peut "
            "inverser cette espérance. Réservé à un capital que tu acceptes de "
            "perdre intégralement."
        ),
    ),
}


# ── Détection des instruments ────────────────────────────────────────────────

# Synthétiques Deriv (espérance négative par construction).
# Couvre les familles réellement seedées : Volatility (R_*), Volatility 1s
# (1HZ*V), Boom/Crash, Jump (JD*), Step (stpRNG), Range Break (RB*),
# Bear/Bull market (RDBEAR/RDBULL).
_DERIV_SYNTHETIC_RE = re.compile(
    r"^(?:"
    r"R_\d{2,3}"                 # R_10 … R_100
    r"|1HZ\d{2,3}V"              # 1HZ10V … 1HZ100V  (absent de l'ancien détecteur)
    r"|BOOM\d{3,4}(?:N)?"        # BOOM300N, BOOM500, BOOM1000
    r"|CRASH\d{3,4}(?:N)?"       # CRASH300N, CRASH500, CRASH1000
    r"|JD\d{2,3}"                # JD10 … JD100
    # Step index : la commande de seed de CETTE plateforme enregistre
    # « STEPINDEX » ; « stpRNG » est le nom côté API Deriv. Les deux doivent
    # matcher, sinon un instrument à espérance négative ressort CORE.
    r"|STEPINDEX"
    r"|STPRNG\d*"
    r"|RB\d{2,3}"                # Range Break
    r"|RDBEAR|RDBULL"            # Bear/Bull market
    r")$"
)

# Paires FX majeures — les plus liquides, spreads les plus serrés.
_FX_MAJORS = frozenset({
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
})

_CORE_ASSET_CLASSES = frozenset({"STOCK", "ETF", "INDEX", "BOND"})
_VOLATILE_ASSET_CLASSES = frozenset({"CRYPTO", "COMMODITY"})


def _normalize_symbol(symbol) -> str:
    """Majuscules, sans séparateurs ni suffixes de cotation (`EUR/USD=X` → `EURUSD`)."""
    if not symbol:
        return ""
    raw = str(symbol).upper().strip()
    for token in ("=X", ".CASH", ".SPOT"):
        raw = raw.replace(token, "")
    return re.sub(r"[^A-Z0-9_]", "", raw)


def is_deriv_synthetic(symbol) -> bool:
    """True si le symbole est un indice synthétique Deriv (espérance négative)."""
    return bool(_DERIV_SYNTHETIC_RE.match(_normalize_symbol(symbol)))


def _matches_fx_major(norm_symbol: str) -> bool:
    """Reconnaît un majeur FX malgré les suffixes de courtier.

    Les brokers MT5 retail suffixent couramment leurs symboles
    (`EURUSDm`, `EURUSD.a`, `EURUSD_raw`, `EURUSD-ECN`). Après normalisation
    il reste `EURUSDM`, `EURUSDA`, `EURUSDRAW`… Sans cette tolérance, la paire
    la plus liquide du monde tomberait en VOLATILE et serait bloquée en mode
    préservation.
    """
    if norm_symbol in _FX_MAJORS:
        return True
    return any(
        norm_symbol.startswith(major) and len(norm_symbol) - len(major) <= 4
        for major in _FX_MAJORS
    )


def classify(asset=None, *, symbol: str = "", exchange: str = "",
             asset_class: str = "") -> str:
    """Retourne le `InstrumentTier` d'un instrument.

    Accepte soit un objet `Asset`, soit les champs bruts (utile pour les
    symboles non encore présents en base). Ordre de résolution volontaire :
    motif de symbole → exchange → asset_class → fail-safe restrictif.
    """
    if asset is not None:
        symbol = symbol or getattr(asset, "symbol", "") or ""
        exchange = exchange or getattr(asset, "exchange", "") or ""
        asset_class = asset_class or getattr(asset, "asset_class", "") or ""

    norm_symbol = _normalize_symbol(symbol)
    exchange_upper = str(exchange or "").upper().strip()
    class_upper = str(asset_class or "").upper().strip()

    # 1. Motif de symbole — prioritaire car asset_class n'est pas fiable
    #    (les synthétiques Deriv sont seedés en "INDEX").
    if is_deriv_synthetic(norm_symbol):
        return InstrumentTier.SPECULATIVE

    # 2. Deriv ne propose que des synthétiques dans cette plateforme : tout
    #    instrument rattaché à cet exchange est traité comme spéculatif.
    if exchange_upper == "DERIV":
        return InstrumentTier.SPECULATIVE

    # 2bis. Paire FX majeure reconnue au symbole seul : `EURUSD` est EURUSD,
    #       quelle que soit (ou en l'absence de) la classe déclarée. Sans cette
    #       règle, un appel sans `asset_class` tomberait sur le fail-safe et
    #       classerait un majeur en SPECULATIVE.
    if _matches_fx_major(norm_symbol):
        return InstrumentTier.CORE

    # 3. Classe d'actif déclarée.
    if class_upper == "FOREX":
        return (
            InstrumentTier.CORE if _matches_fx_major(norm_symbol)
            else InstrumentTier.VOLATILE   # exotiques : spreads larges, vol élevée
        )
    if class_upper in _CORE_ASSET_CLASSES:
        return InstrumentTier.CORE
    if class_upper in _VOLATILE_ASSET_CLASSES:
        return InstrumentTier.VOLATILE

    # 4. Fail-safe : inconnu ⇒ le plus restrictif. En préservation du capital,
    #    on ne suppose jamais qu'un instrument non identifié est sûr.
    return InstrumentTier.SPECULATIVE


def policy_for(asset=None, *, symbol: str = "", exchange: str = "",
               asset_class: str = "") -> TierPolicy:
    """Politique de risque applicable à un instrument."""
    tier = classify(asset, symbol=symbol, exchange=exchange, asset_class=asset_class)
    return POLICIES[tier]


def policy_for_tier(tier: str) -> TierPolicy:
    """Politique d'un niveau donné ; retombe sur SPECULATIVE si inconnu."""
    return POLICIES.get(str(tier or "").upper(), POLICIES[InstrumentTier.SPECULATIVE])


def effective_risk_pct(profile_risk_pct, policy: TierPolicy) -> Decimal:
    """Risque par trade effectif = min(profil utilisateur, plafond du niveau).

    Le plafond de niveau ne peut QUE réduire le risque : un utilisateur ne peut
    pas s'autoriser plus que ce que la classe d'instrument permet.
    """
    try:
        requested = Decimal(str(profile_risk_pct if profile_risk_pct is not None else 0))
    except Exception:
        requested = Decimal("0")
    requested = max(Decimal("0"), requested)
    return min(requested, policy.max_risk_per_trade_pct)
