import pandas as pd
from dataclasses import dataclass, fields

import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
from set_up.config import ETF_SECTOR_MAP
from data.signals._common import (
    attach_sectors,
    python_scalar as _python_scalar,
    rank_pct,
)


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


def calculate_fund_returns(
    tickers: list[str], signal_day: pd.Timestamp
) -> pd.DataFrame:
    lookback = signal_day - pd.Timedelta(days=300)
    prices = fund_repo.get(
        tickers=tickers,
        start_date=str(lookback.date()),
        end_date=str(signal_day.date()),
    )
    prices["date"] = pd.to_datetime(prices["date"])

    rows = []
    for ticker, group in prices.groupby("ticker"):
        close = group.sort_values("date")["close"].values
        rows.append(
            {
                "ticker": ticker,
                "return_5d": (
                    close[-1] / close[-6] - 1 if len(close) >= 6 else float("nan")
                ),
                "return_20d": (
                    close[-1] / close[-21] - 1 if len(close) >= 21 else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows).set_index("ticker")


def build_technical_signals(
    tickers: list[str],
    signal_day: pd.Timestamp,
    benchmark_ticker: str,
    etf_tickers: list[str],
) -> pd.DataFrame:
    """Build point-in-time technical and relative-strength signals."""
    signal_day = pd.Timestamp(signal_day)
    universe = indicators_repo.get_latest_rows(None, signal_day).set_index("ticker")
    if universe.empty:
        return pd.DataFrame()

    missing_tickers = [ticker for ticker in tickers if ticker not in universe.index]
    if missing_tickers:
        raise ValueError(
            f"No indicator data as of {signal_day.date()} for: {missing_tickers}"
        )

    stock_data = attach_sectors(universe.loc[tickers])
    universe_returns = universe[_RETURN_COLS].copy()

    fund_data = calculate_fund_returns([benchmark_ticker] + etf_tickers, signal_day)
    benchmark_data = fund_data.loc[[benchmark_ticker]]
    missing_etfs = [ticker for ticker in etf_tickers if ticker not in fund_data.index]
    if missing_etfs:
        raise ValueError(
            f"No fund price data as of {signal_day.date()} for ETFs: {missing_etfs}"
        )
    etf_data = fund_data.loc[etf_tickers]

    stock_data = _derive_relative_returns(
        stock_data, benchmark_data, etf_data, benchmark_ticker
    )
    return _derive_return_percentiles(stock_data, universe_returns)


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
        self.stock_data = None
        self.load_data()

    def load_data(self) -> None:
        self.stock_data = build_technical_signals(
            self.stock_tickers,
            self.signal_day,
            self.benchmark_ticker,
            self.etf_tickers,
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


