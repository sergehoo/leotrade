import logging
from typing import Iterable, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

SYMBOLS = {
    # =========================
    # CRYPTO
    # =========================
    "crypto": {
        "BTC/USD": "BTC-USD",
        "ETH/USD": "ETH-USD",
        "BNB/USD": "BNB-USD",
        "SOL/USD": "SOL-USD",
        "XRP/USD": "XRP-USD",
        "ADA/USD": "ADA-USD",
        "DOGE/USD": "DOGE-USD",
        "AVAX/USD": "AVAX-USD",
        "MATIC/USD": "MATIC-USD",
        "DOT/USD": "DOT-USD",
    },

    # =========================
    # FOREX
    # =========================
    "forex": {
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "USD/CHF": "CHF=X",
        "AUD/USD": "AUDUSD=X",
        "USD/CAD": "CAD=X",
        "NZD/USD": "NZDUSD=X",
        "EUR/GBP": "EURGBP=X",
    },

    # =========================
    # INDICES
    # =========================
    "indices": {
        "SPX500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DOWJONES": "^DJI",
        "FTSE100": "^FTSE",
        "DAX": "^GDAXI",
        "CAC40": "^FCHI",
        "NIKKEI": "^N225",
        "HANGSENG": "^HSI",
    },

    # =========================
    # COMMODITIES
    # =========================
    "commodities": {
        "XAU/USD (Gold)": "GC=F",
        "XAG/USD (Silver)": "SI=F",
        "WTI Oil": "CL=F",
        "Brent Oil": "BZ=F",
        "Natural Gas": "NG=F",
        "Copper": "HG=F",
    },

    # =========================
    # ACTIONS
    # =========================
    "stocks": {
        "AAPL": "AAPL",
        "MSFT": "MSFT",
        "GOOGL": "GOOGL",
        "AMZN": "AMZN",
        "META": "META",
        "NVDA": "NVDA",
        "TSLA": "TSLA",
        "JPM": "JPM",
        "BAC": "BAC",
        "GS": "GS",
        "KO": "KO",
        "PEP": "PEP",
        "MCD": "MCD",
        "NKE": "NKE",
        "DIS": "DIS",
        "NFLX": "NFLX",
        "INTC": "INTC",
        "AMD": "AMD",
    },
}

# Politique "zéro fake data" : aucun prix simulé n'est jamais renvoyé.
# Si la source de marché est indisponible, on renvoie une liste vide et
# le frontend affiche un état "données indisponibles" explicite.
FALLBACK_MARKET_DATA: list[dict] = []


def _flatten_symbols(categories: Optional[Iterable[str]] = None) -> tuple[dict[str, str], dict[str, str]]:
    """
    Retourne :
    - label_to_symbol : {'BTC/USD': 'BTC-USD', ...}
    - symbol_to_category : {'BTC-USD': 'crypto', ...}
    """
    selected_categories = set(categories) if categories else set(SYMBOLS.keys())

    label_to_symbol: dict[str, str] = {}
    symbol_to_category: dict[str, str] = {}

    for category, symbols in SYMBOLS.items():
        if category not in selected_categories:
            continue

        for label, symbol in symbols.items():
            label_to_symbol[label] = symbol
            symbol_to_category[symbol] = category

    return label_to_symbol, symbol_to_category


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _extract_symbol_frame(df, symbol: str):
    """
    Gère le cas mono-ticker et multi-tickers avec yfinance.download().
    """
    if df is None or df.empty:
        return None

    # MultiIndex columns: ('Close', 'AAPL') ou ('AAPL', 'Close') selon versions/config
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        level0 = set(df.columns.get_level_values(0))
        level1 = set(df.columns.get_level_values(1))

        if symbol in level0:
            try:
                return df[symbol].dropna(how="all")
            except Exception:
                pass

        if symbol in level1:
            try:
                return df.xs(symbol, axis=1, level=1).dropna(how="all")
            except Exception:
                pass

        return None

    # Cas mono ticker
    return df.dropna(how="all")


def get_all_market_data(
    categories: Optional[Iterable[str]] = None,
    use_fallback: bool = True,
    chunk_size: int = 8,
) -> list[dict]:
    """
    Récupère les données de marché en batch avec yfinance.

    Args:
        categories: liste optionnelle des catégories à charger
                    ex: ['crypto', 'forex']
        use_fallback: conservé pour rétro-compatibilité (plus aucun fallback simulé)
        chunk_size: nombre de tickers par batch pour limiter le rate limit

    Returns:
        Liste de dicts:
        [
            {
                'symbol': 'BTC/USD',
                'price': 42381.5,
                'change': 2.34,
                'category': 'crypto',
            },
            ...
        ]
    """
    label_to_symbol, symbol_to_category = _flatten_symbols(categories=categories)

    if not label_to_symbol:
        return []

    reverse_map = {symbol: label for label, symbol in label_to_symbol.items()}
    yahoo_symbols = list(reverse_map.keys())

    data: list[dict] = []

    # On découpe pour réduire le risque de rate limiting
    for batch in _chunked(yahoo_symbols, chunk_size):
        try:
            df = yf.download(
                tickers=batch,
                period="1d",
                interval="1m",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
                prepost=False,
            )
        except Exception as e:
            logger.warning("Erreur batch Yahoo Finance %s: %s", batch, e)
            continue

        for yf_symbol in batch:
            try:
                symbol_df = _extract_symbol_frame(df, yf_symbol)
                if symbol_df is None or symbol_df.empty:
                    continue

                if "Open" not in symbol_df.columns or "Close" not in symbol_df.columns:
                    continue

                symbol_df = symbol_df.dropna(subset=["Open", "Close"])
                if symbol_df.empty:
                    continue

                open_price = float(symbol_df["Open"].iloc[0])
                last_price = float(symbol_df["Close"].iloc[-1])

                change = ((last_price - open_price) / open_price) * 100 if open_price else 0.0

                data.append({
                    "symbol": reverse_map[yf_symbol],
                    "price": round(last_price, 4),
                    "change": round(change, 2),
                    "category": symbol_to_category.get(yf_symbol, "unknown"),
                })

            except Exception as e:
                logger.warning("Erreur %s: %s", yf_symbol, e)

    # Tri propre par catégorie puis symbole
    data.sort(key=lambda x: (x["category"], x["symbol"]))

    # Zéro fake data : pas de substitution simulée si la source échoue.
    return data


_LANDING_SYMBOLS = {
    "crypto": {
        "BTC/USD": "BTC-USD",
        "ETH/USD": "ETH-USD",
        "SOL/USD": "SOL-USD",
        "XRP/USD": "XRP-USD",
    },
    "forex": {
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
    },
    "indices": {
        "SPX500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DOWJONES": "^DJI",
    },
    "commodities": {
        "XAU/USD (Gold)": "GC=F",
        "WTI Oil": "CL=F",
    },
    "stocks": {
        "AAPL": "AAPL",
        "MSFT": "MSFT",
        "NVDA": "NVDA",
        "TSLA": "TSLA",
        "AMZN": "AMZN",
    },
}


def _flatten_specific(symbol_map: dict) -> tuple[dict[str, str], dict[str, str]]:
    label_to_symbol: dict[str, str] = {}
    symbol_to_category: dict[str, str] = {}
    for category, symbols in symbol_map.items():
        for label, sym in symbols.items():
            label_to_symbol[label] = sym
            symbol_to_category[sym] = category
    return label_to_symbol, symbol_to_category


def _fetch_with_map(
    label_to_symbol: dict[str, str],
    symbol_to_category: dict[str, str],
    use_fallback: bool,
    chunk_size: int,
) -> list[dict]:
    if not label_to_symbol:
        return []

    reverse_map = {symbol: label for label, symbol in label_to_symbol.items()}
    yahoo_symbols = list(reverse_map.keys())
    data: list[dict] = []

    for batch in _chunked(yahoo_symbols, chunk_size):
        try:
            df = yf.download(
                tickers=batch,
                period="1d",
                interval="1m",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
                prepost=False,
            )
        except Exception as e:
            logger.warning("Erreur batch Yahoo Finance %s: %s", batch, e)
            continue

        for yf_symbol in batch:
            try:
                symbol_df = _extract_symbol_frame(df, yf_symbol)
                if symbol_df is None or symbol_df.empty:
                    continue
                if "Open" not in symbol_df.columns or "Close" not in symbol_df.columns:
                    continue
                symbol_df = symbol_df.dropna(subset=["Open", "Close"])
                if symbol_df.empty:
                    continue
                open_price = float(symbol_df["Open"].iloc[0])
                last_price = float(symbol_df["Close"].iloc[-1])
                change = ((last_price - open_price) / open_price) * 100 if open_price else 0.0
                data.append({
                    "symbol": reverse_map[yf_symbol],
                    "price": round(last_price, 4),
                    "change": round(change, 2),
                    "category": symbol_to_category.get(yf_symbol, "unknown"),
                })
            except Exception as e:
                logger.warning("Erreur %s: %s", yf_symbol, e)

    data.sort(key=lambda x: (x["category"], x["symbol"]))

    # Zéro fake data : pas de substitution simulée si la source échoue.
    return data


def get_landing_market_data() -> list[dict]:
    """
    Version légère pour la landing page.

    FIX: previously mutated the module-level ``SYMBOLS`` global, causing
    a race condition when multiple landing requests overlapped (different
    requests would see partial/wrong symbol sets). Now uses a local map
    and a 60s in-process cache to dampen Yahoo Finance rate limits.
    """
    # 60s shared cache across requests of the same worker
    try:
        from django.core.cache import cache as django_cache

        cached = django_cache.get("leotrade:market:landing")
        if cached is not None:
            return cached
    except Exception:
        django_cache = None

    label_to_symbol, symbol_to_category = _flatten_specific(_LANDING_SYMBOLS)
    data = _fetch_with_map(
        label_to_symbol=label_to_symbol,
        symbol_to_category=symbol_to_category,
        use_fallback=True,
        chunk_size=6,
    )

    if django_cache is not None and data:
        try:
            django_cache.set("leotrade:market:landing", data, timeout=60)
        except Exception:
            pass

    return data
