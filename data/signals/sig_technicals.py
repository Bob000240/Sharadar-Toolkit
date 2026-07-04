import pandas as pd
from dataclasses import dataclass, fields

import database.market.equity_repo as equity_repo
import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
import database.market.tickers_repo as tickers_repo
from data.live_equity import MarketData
from data.indicators import compute_indicators
from set_up.config import ETF_SECTOR_MAP
from data.signals._common import python_scalar as _python_scalar, rank_pct


_RETURN_COLS = ["return_5d", "return_20d", "return_60d", "return_252d"]


def _derive_relative_returns(stock_data, benchmark_data, etf_data, benchmark_ticker):
    """Add benchmark excess returns and sector-relative returns (vs sector ETF)."""
    bench_5d = benchmark_data.loc[benchmark_ticker, "return_5d"]
    bench_20d = benchmark_data.loc[benchmark_ticker, "return_20d"]
    stock_data["excess_return_5d"] = stock_data["return_5d"] - bench_5d
    stock_data["excess_return_20d"] = stock_data["return_20d"] - bench_20d
    etf_returns = etf_data[["return_5d", "return_20d"]].copy()
    etf_returns.index = etf_returns.index.map(ETF_SECTOR_MAP)
    stock_data["sector_relative_5d"] = stock_data["return_5d"] - stock_data[
        "sector"
    ].map(etf_returns["return_5d"])
    stock_data["sector_relative_20d"] = stock_data["return_20d"] - stock_data[
        "sector"
    ].map(etf_returns["return_20d"])
    return stock_data


def _derive_return_percentiles(stock_data, universe_returns):
    """Rank each return horizon across the full universe (batch values overlaid)."""
    universe = universe_returns.copy()
    universe.loc[stock_data.index, _RETURN_COLS] = stock_data[_RETURN_COLS]
    for col in _RETURN_COLS:
        stock_data[f"{col}_percentile"] = rank_pct(universe[col]).reindex(
            stock_data.index
        )
    return stock_data


@dataclass
class TechnicalsSnapshot:
    ticker: str
    signal_day: pd.Timestamp

    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float

    excess_return_5d: float
    excess_return_20d: float

    sector_relative_5d: float
    sector_relative_20d: float
    sector: str

    price: float
    sma_20: float
    sma_50: float
    sma_200: float
    high_52w: float
    rolling_20d_high: float
    pct_from_52w_high: float

    r_squared_60d: float
    trend_slope_60d: float

    volume_ratio: float
    dollar_volume_20d_avg: float

    atr_14: float
    atr_pct: float
    volatility_20: float
    vol_adjusted_momentum: float

    return_5d_percentile: float
    return_20d_percentile: float
    return_60d_percentile: float
    return_252d_percentile: float

    drawdown_from_recent_high: float
    consolidation_tightness: float

    pct_from_sma_20: float
    pct_from_sma_50: float

    ema_9: float
    ema_21: float
    ema_crossover_days_ago: float  # days since last EMA cross; NaN until first cross

    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float

    def __post_init__(self) -> None:
        for field in fields(self):
            setattr(self, field.name, _python_scalar(getattr(self, field.name)))

    @property
    def momentum_consistency(self) -> int:
        return sum(
            [
                self.return_5d > 0,
                self.return_20d > 0,
                self.return_60d > 0,
                self.return_252d > 0,
            ]
        )

    @property
    def above_sma_200(self) -> bool:
        return self.price > self.sma_200

    @property
    def above_sma_50(self) -> bool:
        return self.price > self.sma_50

    @property
    def new_52w_high(self) -> bool:
        return self.pct_from_52w_high >= 0

    @property
    def slope_x_r2(self) -> float:
        return self.trend_slope_60d * self.r_squared_60d

    def risk_flags(self) -> dict[str, bool]:
        return {
            "overbought": self.rsi_14 > 70,
            "low_liquidity": self.dollar_volume_20d_avg < 1_000_000,
            "extended_drawdown": self.pct_from_52w_high < -0.30,
            "volatile_base": self.consolidation_tightness > 1.5,
            "high_volatility": self.volatility_20 > 0.04,
            "atr_elevated": self.atr_pct > 0.04,
        }


class TechnicalsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_tickers: list[str],
        benchmark_ticker: str,
        etf_tickers: list[str],
    ):
        self.signal_day = signal_day
        self.stock_tickers = stock_tickers
        self.benchmark_ticker = benchmark_ticker
        self.etf_tickers = etf_tickers
        self.all_tickers = stock_tickers + [benchmark_ticker] + etf_tickers
        self.stock_data = None
        self.benchmark_data = None
        self.etf_data = None
        self._universe_returns = None
        self.load_data()

    def _compute_live(self, tickers: list[str]) -> pd.DataFrame:
        lookback_start = self.signal_day - pd.Timedelta(days=400)
        yesterday = self.signal_day - pd.Timedelta(days=1)
        ohlcv = equity_repo.get(
            tickers=tickers,
            start_date=str(lookback_start.date()),
            end_date=str(yesterday.date()),
        )
        ohlcv["date"] = pd.to_datetime(ohlcv["date"])

        live = MarketData().get_live_snapshot(tickers)
        if not live.empty:
            today = pd.Timestamp(self.signal_day.date())
            live_rows = live.reset_index().rename(columns={"symbol": "ticker"})
            live_rows["date"] = today
            ohlcv = pd.concat([ohlcv, live_rows], ignore_index=True)

        ohlcv = ohlcv.sort_values(["ticker", "date"])
        rows = []
        for tkr, group in ohlcv.groupby("ticker", sort=False):
            ind = compute_indicators(group.reset_index(drop=True))
            if not ind.empty:
                last = ind.iloc[-1].to_dict()
                last["ticker"] = tkr
                rows.append(last)
        return pd.DataFrame(rows).set_index("ticker")

    def _fund_returns(self, tickers: list[str]) -> pd.DataFrame:
        lookback = self.signal_day - pd.Timedelta(days=300)
        prices = fund_repo.get(
            tickers=tickers,
            start_date=str(lookback.date()),
            end_date=str(self.signal_day.date()),
        )
        prices["date"] = pd.to_datetime(prices["date"])
        rows = []
        for tkr, grp in prices.groupby("ticker"):
            c = grp.sort_values("date")["close"].values
            rows.append(
                {
                    "ticker": tkr,
                    "return_5d": (c[-1] / c[-6] - 1) if len(c) >= 6 else float("nan"),
                    "return_20d": (c[-1] / c[-21] - 1) if len(c) >= 21 else float("nan"),
                }
            )
        return pd.DataFrame(rows).set_index("ticker")

    def load_data(self, live: bool = False, tickers: list[str] | None = None) -> None:
        if live and tickers:
            fresh = self._compute_live(tickers)
            for tkr in fresh.index:
                if tkr not in self.stock_data.index:
                    continue
                for col in fresh.columns:
                    if col in self.stock_data.columns:
                        self.stock_data.at[tkr, col] = fresh.at[tkr, col]
        else:
            # Load the full indicators universe so return percentiles are ranked
            # market-wide (independent of the request batch), then take the batch.
            universe = indicators_repo.get_latest(None, self.signal_day).set_index(
                "ticker"
            )
            self._universe_returns = universe[_RETURN_COLS].copy()

            missing = [t for t in self.stock_tickers if t not in universe.index]
            if missing:
                raise ValueError(
                    f"No indicator data as of {self.signal_day.date()} for: {missing}"
                )
            self.stock_data = universe.loc[self.stock_tickers].copy()
            sector_map = tickers_repo.get(tickers=self.stock_tickers)[
                ["ticker", "sector"]
            ].set_index("ticker")["sector"]
            self.stock_data["sector"] = sector_map.reindex(self.stock_data.index)

            fund_data = self._fund_returns([self.benchmark_ticker] + self.etf_tickers)
            self.benchmark_data = fund_data.loc[[self.benchmark_ticker]]
            missing_etfs = [t for t in self.etf_tickers if t not in fund_data.index]
            if missing_etfs:
                raise ValueError(
                    f"No fund price data as of {self.signal_day.date()} for ETFs: {missing_etfs}"
                )
            self.etf_data = fund_data.loc[self.etf_tickers]

        self.stock_data = _derive_relative_returns(
            self.stock_data, self.benchmark_data, self.etf_data, self.benchmark_ticker
        )
        self.stock_data = _derive_return_percentiles(
            self.stock_data, self._universe_returns
        )

    def get(self, ticker: str, col: str):
        if ticker not in self.stock_data.index:
            raise ValueError(f"Ticker {ticker} not in stock_data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in stock_data")
        return self.stock_data.loc[ticker, col]

    def build_snapshot(self, ticker: str) -> TechnicalsSnapshot:
        if ticker not in self.stock_data.index:
            raise ValueError(f"Ticker {ticker} not in stock_data")
        row = self.stock_data.loc[ticker]

        return TechnicalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            return_5d=row["return_5d"],
            return_20d=row["return_20d"],
            return_60d=row["return_60d"],
            return_252d=row["return_252d"],
            excess_return_5d=row["excess_return_5d"],
            excess_return_20d=row["excess_return_20d"],
            sector_relative_5d=row["sector_relative_5d"],
            sector_relative_20d=row["sector_relative_20d"],
            sector=row["sector"],
            price=row["close"],
            sma_20=row["sma_20"],
            sma_50=row["sma_50"],
            sma_200=row["sma_200"],
            high_52w=row["high_52w"],
            rolling_20d_high=row["rolling_20d_high"],
            pct_from_52w_high=row["pct_from_52w_high"],
            r_squared_60d=row["r_squared_60d"],
            trend_slope_60d=row["trend_slope_60d"],
            volume_ratio=row["volume_ratio"],
            dollar_volume_20d_avg=row["dollar_volume_20d_avg"],
            atr_14=row["atr_14"],
            atr_pct=row["atr_pct"],
            volatility_20=row["volatility_20"],
            vol_adjusted_momentum=row["vol_adjusted_momentum"],
            return_5d_percentile=row["return_5d_percentile"],
            return_20d_percentile=row["return_20d_percentile"],
            return_60d_percentile=row["return_60d_percentile"],
            return_252d_percentile=row["return_252d_percentile"],
            drawdown_from_recent_high=row["drawdown_from_recent_high"],
            consolidation_tightness=row["consolidation_tightness"],
            pct_from_sma_20=row["pct_from_sma_20"],
            pct_from_sma_50=row["pct_from_sma_50"],
            ema_9=row["ema_9"],
            ema_21=row["ema_21"],
            ema_crossover_days_ago=row["ema_crossover_days_ago"],
            rsi_14=row["rsi_14"],
            macd=row["macd"],
            macd_signal=row["macd_signal"],
            macd_hist=row["macd_hist"],
        )


def print_snapshot_report(snapshot: TechnicalsSnapshot) -> None:
    sections = {
        "Risk Flags": snapshot.risk_flags(),
    }

    print(f"\n=== {snapshot.ticker} | {snapshot.signal_day.date()} ===")
    for title, values in sections.items():
        print(f"{title}: {values}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    stock_tickers = ["AAPL", "MSFT", "GOOGL"]
    benchmark_ticker = "SPY"
    etf_tickers = list(ETF_SECTOR_MAP.keys())

    model = TechnicalsModel(signal_day, stock_tickers, benchmark_ticker, etf_tickers)
    for ticker in stock_tickers:
        print_snapshot_report(model.build_snapshot(ticker))
