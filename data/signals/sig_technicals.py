import pandas as pd
from dataclasses import dataclass

import database.market.equity_repo as equity_repo
import database.market.indicators_repo as indicators_repo
import database.market.tickers_repo as tickers_repo
from data.live_equity import MarketData
from data.indicators import compute_indicators


@dataclass
class TechnicalsSnapshot:
    ticker: str
    signal_day: pd.Timestamp

    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float
    momentum_consistency: int

    excess_return_5d: float
    excess_return_20d: float

    sector_relative_5d: float
    sector_relative_20d: float
    sector: str

    price: float
    above_sma_200: bool
    above_sma_50: bool
    pct_from_52w_high: float
    new_52w_high: bool

    r_squared_60d: float
    trend_slope_60d: float
    slope_x_r2: float

    momentum_accel_20_60: float
    momentum_accel_5_20: float

    volume_ratio: float
    dollar_volume_20d_avg: float

    vol_adjusted_momentum: float

    return_5d_percentile: float
    return_20d_percentile: float
    return_60d_percentile: float
    return_252d_percentile: float

    price_vs_20d_high: float
    consolidation_tightness: float

    pct_from_sma_20: float
    pct_from_sma_50: float

    ema_9: float
    ema_21: float
    ema_9_above_21: bool
    ema_crossover_days_ago: int

    rsi_14: float
    macd_hist: float


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
        self._load_data()

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

    def _from_db(self) -> pd.DataFrame:
        df = indicators_repo.get_latest(self.all_tickers, self.signal_day)
        return df.set_index("ticker")

    def _load_data(self, live: bool = False, tickers: list[str] | None = None) -> None:
        if live and tickers:
            fresh = self._compute_live(tickers)
            for tkr in fresh.index:
                if tkr not in self.stock_data.index:
                    continue
                for col in fresh.columns:
                    if col in self.stock_data.columns:
                        self.stock_data.at[tkr, col] = fresh.at[tkr, col]
                self.stock_data.at[tkr, "above_sma_50"]  = fresh.at[tkr, "close"] > fresh.at[tkr, "sma_50"]
                self.stock_data.at[tkr, "above_sma_200"] = fresh.at[tkr, "close"] > fresh.at[tkr, "sma_200"]
        else:
            all_indicators = self._from_db()
            sector_map = (
                tickers_repo.get(tickers=self.all_tickers)[["ticker", "sector"]]
                .set_index("ticker")["sector"]
            )
            all_indicators["sector"] = sector_map
            all_indicators["above_sma_50"]  = all_indicators["close"] > all_indicators["sma_50"]
            all_indicators["above_sma_200"] = all_indicators["close"] > all_indicators["sma_200"]
            self.stock_data     = all_indicators.loc[self.stock_tickers].copy()
            self.benchmark_data = all_indicators.loc[[self.benchmark_ticker]].copy()
            self.etf_data       = all_indicators.loc[self.etf_tickers].copy()

        bench_5d  = self.benchmark_data.loc[self.benchmark_ticker, "return_5d"]
        bench_20d = self.benchmark_data.loc[self.benchmark_ticker, "return_20d"]
        self.stock_data["excess_return_5d"]  = self.stock_data["return_5d"]  - bench_5d
        self.stock_data["excess_return_20d"] = self.stock_data["return_20d"] - bench_20d

        etf_returns = self.etf_data[["return_5d", "return_20d"]].copy()
        etf_returns.index = all_indicators.loc[self.etf_tickers, "sector"]
        self.stock_data["sector_relative_5d"]  = self.stock_data["return_5d"]  - self.stock_data["sector"].map(etf_returns["return_5d"])
        self.stock_data["sector_relative_20d"] = self.stock_data["return_20d"] - self.stock_data["sector"].map(etf_returns["return_20d"])

        for col in ["return_5d", "return_20d", "return_60d", "return_252d"]:
            self.stock_data[f"{col}_percentile"] = self.stock_data[col].rank(pct=True) * 100

    def get(self, ticker: str, col: str):
        if ticker not in self.stock_data.index:
            raise ValueError(f"Ticker {ticker} not in stock_data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in stock_data")
        return self.stock_data.loc[ticker, col]

    def build_snapshot(self, ticker: str) -> TechnicalsSnapshot:
        return TechnicalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            return_5d=self.get(ticker, "return_5d"),
            return_20d=self.get(ticker, "return_20d"),
            return_60d=self.get(ticker, "return_60d"),
            return_252d=self.get(ticker, "return_252d"),
            momentum_consistency=sum([
                self.get(ticker, "return_5d") > 0,
                self.get(ticker, "return_20d") > 0,
                self.get(ticker, "return_60d") > 0,
                self.get(ticker, "return_252d") > 0,
            ]),
            excess_return_5d=self.get(ticker, "excess_return_5d"),
            excess_return_20d=self.get(ticker, "excess_return_20d"),
            sector_relative_5d=self.get(ticker, "sector_relative_5d"),
            sector_relative_20d=self.get(ticker, "sector_relative_20d"),
            sector=self.get(ticker, "sector"),
            price=self.get(ticker, "close"),
            above_sma_200=self.get(ticker, "above_sma_200"),
            above_sma_50=self.get(ticker, "above_sma_50"),
            pct_from_52w_high=self.get(ticker, "pct_from_52w_high"),
            new_52w_high=self.get(ticker, "new_52w_high"),
            r_squared_60d=self.get(ticker, "r_squared_60d"),
            trend_slope_60d=self.get(ticker, "trend_slope_60d"),
            slope_x_r2=self.get(ticker, "slope_x_r2"),
            momentum_accel_20_60=self.get(ticker, "momentum_accel_20_60"),
            momentum_accel_5_20=self.get(ticker, "momentum_accel_5_20"),
            volume_ratio=self.get(ticker, "volume_ratio"),
            dollar_volume_20d_avg=self.get(ticker, "dollar_volume_20d_avg"),
            vol_adjusted_momentum=self.get(ticker, "vol_adjusted_momentum"),
            return_5d_percentile=self.get(ticker, "return_5d_percentile"),
            return_20d_percentile=self.get(ticker, "return_20d_percentile"),
            return_60d_percentile=self.get(ticker, "return_60d_percentile"),
            return_252d_percentile=self.get(ticker, "return_252d_percentile"),
            price_vs_20d_high=self.get(ticker, "price_vs_20d_high"),
            consolidation_tightness=self.get(ticker, "consolidation_tightness"),
            pct_from_sma_20=self.get(ticker, "pct_from_sma_20"),
            pct_from_sma_50=self.get(ticker, "pct_from_sma_50"),
            ema_9=self.get(ticker, "ema_9"),
            ema_21=self.get(ticker, "ema_21"),
            ema_9_above_21=self.get(ticker, "ema_9_above_21"),
            ema_crossover_days_ago=self.get(ticker, "ema_crossover_days_ago"),
            rsi_14=self.get(ticker, "rsi_14"),
            macd_hist=self.get(ticker, "macd_hist"),
        )
