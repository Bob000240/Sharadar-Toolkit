import database.descriptors_repository as descriptor_repo
import database.market_repository as market_repo
import database.indicator_repository as indicator_repo
from data_det.raw_data.market_data import MarketData
from data_det.processed_data.indicators import compute_indicators

import pandas as pd
from dataclasses import dataclass


@dataclass
class TechnicalsSnapshot:
    symbol: str
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


# Alias so any remaining references survive until pre_RS is rewritten
MomentumSnapshot = TechnicalsSnapshot


class TechnicalsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str] | str,
        benchmark_symbol: str,
        etf_symbols: list[str] | str,
    ):
        self.signal_day = signal_day
        self.stock_symbols = stock_symbols
        self.benchmark_symbol = benchmark_symbol
        self.etf_symbols = etf_symbols
        self.all_symbols = self.stock_symbols + [self.benchmark_symbol] + self.etf_symbols
        self.stock_data = None
        self.benchmark_data = None
        self.etf_data = None
        self._load_data()

    def _compute_live(self, symbols: list[str]) -> pd.DataFrame:
        lookback_start = self.signal_day - pd.Timedelta(days=400)
        yesterday = self.signal_day - pd.Timedelta(days=1)
        ohlcv = market_repo.get_OHLCV(symbols, lookback_start, yesterday)
        ohlcv["date"] = pd.to_datetime(ohlcv["date"])
        live = MarketData().get_live_snapshot(symbols)
        if not live.empty:
            today = pd.Timestamp(self.signal_day.date())
            live_rows = live.reset_index().rename(columns={"index": "symbol"})
            live_rows["date"] = today
            ohlcv = pd.concat([ohlcv, live_rows], ignore_index=True)
        ohlcv = ohlcv.sort_values(["symbol", "date"])
        rows = []
        for sym, group in ohlcv.groupby("symbol", sort=False):
            ind = compute_indicators(group.reset_index(drop=True))
            if not ind.empty:
                last = ind.iloc[-1].to_dict()
                last["symbol"] = sym
                rows.append(last)
        return pd.DataFrame(rows).set_index("symbol")

    def _from_db(self) -> pd.DataFrame:
        yesterday = self.signal_day - pd.Timedelta(days=1)
        df = indicator_repo.get_latest_indicators(self.all_symbols, yesterday)
        return df.set_index("symbol")

    def _load_data(self, live: bool = False, symbols: list[str] | None = None) -> None:
        if live and symbols:
            all_indicators = self._compute_live(symbols)
            for sym in all_indicators.index:
                if sym not in self.stock_data.index:
                    continue
                for col in all_indicators.columns:
                    if col in self.stock_data.columns:
                        self.stock_data.at[sym, col] = all_indicators.at[sym, col]
                self.stock_data.at[sym, "above_sma_50"]  = all_indicators.at[sym, "close"] > all_indicators.at[sym, "sma_50"]
                self.stock_data.at[sym, "above_sma_200"] = all_indicators.at[sym, "close"] > all_indicators.at[sym, "sma_200"]
        else:
            all_indicators = self._from_db()
            sector_mapping = descriptor_repo.get_descriptors(self.all_symbols)[["symbol", "sector"]].set_index("symbol")
            all_indicators["sector"] = sector_mapping["sector"]
            all_indicators["above_sma_50"]  = all_indicators["close"] > all_indicators["sma_50"]
            all_indicators["above_sma_200"] = all_indicators["close"] > all_indicators["sma_200"]
            self.stock_data     = all_indicators.loc[self.stock_symbols].copy()
            self.benchmark_data = all_indicators.loc[[self.benchmark_symbol]].copy()
            self.etf_data       = all_indicators.loc[self.etf_symbols].copy()

        bench_5d  = self.benchmark_data.loc[self.benchmark_symbol, "return_5d"]
        bench_20d = self.benchmark_data.loc[self.benchmark_symbol, "return_20d"]
        self.stock_data["excess_return_5d"]  = self.stock_data["return_5d"]  - bench_5d
        self.stock_data["excess_return_20d"] = self.stock_data["return_20d"] - bench_20d
        etf_returns = self.etf_data.set_index("sector")
        self.stock_data["sector_relative_5d"]  = self.stock_data["return_5d"]  - self.stock_data["sector"].map(etf_returns["return_5d"])
        self.stock_data["sector_relative_20d"] = self.stock_data["return_20d"] - self.stock_data["sector"].map(etf_returns["return_20d"])
        for col in ["return_5d", "return_20d", "return_60d", "return_252d"]:
            self.stock_data[f"{col}_percentile"] = self.stock_data[col].rank(pct=True) * 100

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in stock_data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in stock_data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> TechnicalsSnapshot:
        return TechnicalsSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            return_5d=self.get(symbol, "return_5d"),
            return_20d=self.get(symbol, "return_20d"),
            return_60d=self.get(symbol, "return_60d"),
            return_252d=self.get(symbol, "return_252d"),
            momentum_consistency=sum([
                self.get(symbol, "return_5d") > 0,
                self.get(symbol, "return_20d") > 0,
                self.get(symbol, "return_60d") > 0,
                self.get(symbol, "return_252d") > 0,
            ]),
            excess_return_5d=self.get(symbol, "excess_return_5d"),
            excess_return_20d=self.get(symbol, "excess_return_20d"),
            sector_relative_5d=self.get(symbol, "sector_relative_5d"),
            sector_relative_20d=self.get(symbol, "sector_relative_20d"),
            sector=self.get(symbol, "sector"),
            price=self.get(symbol, "close"),
            above_sma_200=self.get(symbol, "above_sma_200"),
            above_sma_50=self.get(symbol, "above_sma_50"),
            pct_from_52w_high=self.get(symbol, "pct_from_52w_high"),
            new_52w_high=self.get(symbol, "new_52w_high"),
            r_squared_60d=self.get(symbol, "r_squared_60d"),
            trend_slope_60d=self.get(symbol, "trend_slope_60d"),
            slope_x_r2=self.get(symbol, "slope_x_r2"),
            momentum_accel_20_60=self.get(symbol, "momentum_accel_20_60"),
            momentum_accel_5_20=self.get(symbol, "momentum_accel_5_20"),
            volume_ratio=self.get(symbol, "volume_ratio"),
            dollar_volume_20d_avg=self.get(symbol, "dollar_volume_20d_avg"),
            vol_adjusted_momentum=self.get(symbol, "vol_adjusted_momentum"),
            return_5d_percentile=self.get(symbol, "return_5d_percentile"),
            return_20d_percentile=self.get(symbol, "return_20d_percentile"),
            return_60d_percentile=self.get(symbol, "return_60d_percentile"),
            return_252d_percentile=self.get(symbol, "return_252d_percentile"),
            price_vs_20d_high=self.get(symbol, "price_vs_20d_high"),
            consolidation_tightness=self.get(symbol, "consolidation_tightness"),
            pct_from_sma_20=self.get(symbol, "pct_from_sma_20"),
            pct_from_sma_50=self.get(symbol, "pct_from_sma_50"),
            ema_9=self.get(symbol, "ema_9"),
            ema_21=self.get(symbol, "ema_21"),
            ema_9_above_21=self.get(symbol, "ema_9_above_21"),
            ema_crossover_days_ago=self.get(symbol, "ema_crossover_days_ago"),
            rsi_14=self.get(symbol, "rsi_14"),
            macd_hist=self.get(symbol, "macd_hist"),
        )


# Alias so any remaining references survive until pre_RS is rewritten
MomentumFactorsModel = TechnicalsModel
