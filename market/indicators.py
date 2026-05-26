import pandas as pd
import ta


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rsi_14"] = ta.momentum.RSIIndicator(close=out["close"], window=14).rsi()
    macd = ta.trend.MACD(close=out["close"])
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["sma_20"] = ta.trend.SMAIndicator(close=out["close"], window=20).sma_indicator()
    out["sma_50"] = ta.trend.SMAIndicator(close=out["close"], window=50).sma_indicator()
    out["atr_14"] = ta.volatility.AverageTrueRange(
        high=out["high"], low=out["low"], close=out["close"], window=14
    ).average_true_range()
    bb = ta.volatility.BollingerBands(close=out["close"], window=20, window_dev=2)
    out["bb_high"] = bb.bollinger_hband()
    out["bb_low"] = bb.bollinger_lband()
    out["returns_1"] = out["close"].pct_change(1)
    out["returns_5"] = out["close"].pct_change(5)
    out["volatility_20"] = out["returns_1"].rolling(20).std()
    return out