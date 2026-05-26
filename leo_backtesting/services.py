import pandas as pd
from backtesting import Backtest, Strategy as BTStrategy
from market.models import Candle
from .models import BacktestRun


class SmaCrossStrategy(BTStrategy):
    n1 = 20
    n2 = 50

    def init(self):
        close = self.data.Close
        self.sma1 = self.I(lambda x: pd.Series(x).rolling(self.n1).mean(), close)
        self.sma2 = self.I(lambda x: pd.Series(x).rolling(self.n2).mean(), close)

    def next(self):
        if self.sma1[-1] > self.sma2[-1] and not self.position:
            self.buy()
        elif self.sma1[-1] < self.sma2[-1] and self.position:
            self.position.close()


def run_backtest(strategy):
    candles = Candle.objects.filter(asset=strategy.asset, timeframe=strategy.timeframe).order_by("open_time")
    df = pd.DataFrame(list(candles.values("open_time", "open", "high", "low", "close", "volume")))
    if df.empty:
        return BacktestRun.objects.create(
            strategy=strategy,
            name=f"BT - {strategy.name}",
            start_date=pd.Timestamp.today().date(),
            end_date=pd.Timestamp.today().date(),
            status="FAILED",
            metrics={"error": "No candle data"},
        )

    df.rename(columns={
        "open_time": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }, inplace=True)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col])
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)

    bt = Backtest(df, SmaCrossStrategy, cash=10_000, commission=0.001, exclusive_orders=True)
    stats = bt.run()
    curve = []
    if "_equity_curve" in stats:
        curve = stats["_equity_curve"].reset_index().to_dict(orient="records")

    return BacktestRun.objects.create(
        strategy=strategy,
        name=f"BT - {strategy.name}",
        start_date=df.index.min().date(),
        end_date=df.index.max().date(),
        initial_cash=10000,
        commission=0.001,
        status="DONE",
        metrics={k: (float(v) if hasattr(v, "__float__") else str(v)) for k, v in stats.items() if not str(k).startswith("_")},
        equity_curve=curve,
    )