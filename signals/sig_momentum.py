import database.indicator_repository as indicator_repo
import database.sector_data_repository as sector_repo
import database.market_data_repository as market_repo

import pandas as pd
from dataclasses import dataclass
from signals.sig_base import SignalSnapshot, SignalModel


@dataclass
class MomentumSnapshot(SignalSnapshot):
    """Raw momentum data for a single stock."""

    # Identity
    symbol: str
    signal_day: pd.Timestamp

    # Absolute momentum
    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float

    # Composite momentum
    momentum_composite_percentile: float
    momentum_consistency: int
    # Count of positive periods across 5d/20d/60d/252d (0–4)

    # Benchmark-relative momentum (vs SPY)
    excess_return_5d: float
    excess_return_20d: float

    # Sector-relative momentum
    sector_relative_5d: float
    sector_relative_20d: float
    sector: str

    # Trend / structure
    price: float
    above_sma_200: bool
    pct_from_52w_high: float
    new_52w_high: bool

    # Trend quality
    r_squared_60d: float
    # R² of price vs time regression (0–1)

    trend_slope_60d: float
    # Annualized regression slope over 60d

    slope_x_r2: float
    # trend_slope_60d * r_squared_60d

    drawdown_from_recent_high: float
    # Max drawdown over trailing 20d

    # Momentum acceleration
    momentum_accel_20_60: float
    # return_20d - return_60d

    momentum_accel_5_20: float
    # return_5d - return_20d

    # Volume / participation
    volume_ratio: float
    # current volume / 50d avg volume

    dollar_volume_20d_avg: float

    # Risk / volatility
    volatility_20: float
    atr_pct: float

    vol_adjusted_momentum: float
    # return_60d / volatility_20

    # Universe-relative ranks (0–100)
    return_5d_percentile: float
    return_20d_percentile: float
    return_60d_percentile: float
    return_252d_percentile: float

    def to_agent_prompt(self):
        """
        Returns a plain-English summary of all momentum signals for the AI agent.
        Designed to be most LLM token friendly using NLP.
        """
        def pct(v: float):
            return f"{v:+.1%}"

        def rank(v: float):
            return f"{v:.0f}th percentile"

        lines = [
            f"MOMENTUM ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector} | Current price: ${self.price:.2f}",
            "",
            "--- ABSOLUTE MOMENTUM (raw price performance) ---",
            f"  5-day return:   {pct(self.return_5d)}   (universe rank: {rank(self.return_5d_percentile)})",
            f" 20-day return:   {pct(self.return_20d)}   (universe rank: {rank(self.return_20d_percentile)})",
            f" 60-day return:   {pct(self.return_60d)}   (universe rank: {rank(self.return_60d_percentile)})",
            f"252-day return:   {pct(self.return_252d)}   (universe rank: {rank(self.return_252d_percentile)})",
            f"  Composite rank: {rank(self.momentum_composite_percentile)} - average across all four windows",
            f"  Consistency:    {self.momentum_consistency}/4 periods positive (5d / 20d / 60d / 252d)",
            "",
            "--- BENCHMARK-RELATIVE MOMENTUM (vs S&P 500) ---",
            f"  5-day excess return:  {pct(self.excess_return_5d)}  (positive = outperforming the market)",
            f" 20-day excess return:  {pct(self.excess_return_20d)}",
            "",
            "--- SECTOR-RELATIVE MOMENTUM (vs sector ETF) ---",
            f"  5-day vs sector:  {pct(self.sector_relative_5d)}  (positive = outperforming sector peers)",
            f" 20-day vs sector:  {pct(self.sector_relative_20d)}",
            "",
            "--- TREND STRUCTURE ---",
            f"  Above 200-day moving average: {self.above_sma_200}  (True = long-term uptrend intact)",
            f"  Distance from 52-week high:   {pct(self.pct_from_52w_high)}  (0% = at new high)",
            f"  New 52-week high today:        {self.new_52w_high}",
            f"  60-day trend R^2:               {self.r_squared_60d:.2f}  (0 = chaotic, 1 = perfectly linear climb)",
            f"  60-day annualized trend slope: {pct(self.trend_slope_60d)} per year",
            f"  Trend quality score (slope*R^2):{self.slope_x_r2:.3f}  (higher = stronger, smoother uptrend)",
            f"  Drawdown from 20-day high:     {pct(self.drawdown_from_recent_high)}  (0% = at recent peak)",
            "",
            "--- MOMENTUM ACCELERATION ---",
            f"  Short-term (5d vs 20d):   {pct(self.momentum_accel_5_20)}  (positive = recent acceleration)",
            f"  Medium-term (20d vs 60d): {pct(self.momentum_accel_20_60)}  (positive = broadening momentum)",
            "",
            "--- VOLUME & LIQUIDITY ---",
            f"  Volume ratio (vs 50-day avg): {self.volume_ratio:.2f}x  (>1 = above-average participation)",
            f"  Avg daily dollar volume (20d): ${self.dollar_volume_20d_avg:,.0f}",
            "",
            "--- RISK & VOLATILITY ---",
            f"  20-day realised volatility (annualised): {self.volatility_20:.1%}",
            f"  ATR as % of price:                       {self.atr_pct:.2%}",
            f"  Risk-adjusted momentum (return / vol):   {self.vol_adjusted_momentum:.2f}",
        ]
        return "\n".join(lines)


class MomentumFactorsModel(SignalModel):
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

        self.all_symbols = (
            self.stock_symbols + [self.benchmark_symbol] + self.etf_symbols
        )

        self.stock_data = None
        self.benchmark_data = None
        self.etf_data = None
        self._load_data()

    def _load_data(self):
        all_OHLCV = market_repo.get_latest_OHLCV(self.all_symbols, self.signal_day)
        all_indicators = indicator_repo.get_latest_indicators(
            self.all_symbols, self.signal_day
        )
        sector_mapping = sector_repo.get_sector_mapping(self.all_symbols)

        all_OHLCV = all_OHLCV.set_index("symbol")
        all_indicators = all_indicators.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")

        all_indicators["close"] = all_OHLCV["close"]
        all_indicators["sector"] = sector_mapping["sector"]

        self.stock_data = all_indicators.loc[self.stock_symbols].copy()
        self.benchmark_data = all_indicators.loc[[self.benchmark_symbol]].copy()
        self.etf_data = all_indicators.loc[self.etf_symbols].copy()

        bench_5d = self.benchmark_data.loc[self.benchmark_symbol, "return_5d"]
        bench_20d = self.benchmark_data.loc[self.benchmark_symbol, "return_20d"]
        self.stock_data["excess_return_5d"] = self.stock_data["return_5d"] - bench_5d
        self.stock_data["excess_return_20d"] = self.stock_data["return_20d"] - bench_20d

        etf_returns = self.etf_data.set_index("sector")
        self.stock_data["sector_relative_5d"] = self.stock_data[
            "return_5d"
        ] - self.stock_data["sector"].map(etf_returns["return_5d"])
        self.stock_data["sector_relative_20d"] = self.stock_data[
            "return_20d"
        ] - self.stock_data["sector"].map(etf_returns["return_20d"])

        for col in ["return_5d", "return_20d", "return_60d", "return_252d"]:
            self.stock_data[f"{col}_percentile"] = (
                self.stock_data[col].rank(pct=True) * 100
            )

        self.stock_data["momentum_composite_percentile"] = (
            self.stock_data["return_5d_percentile"]
            + self.stock_data["return_20d_percentile"]
            + self.stock_data["return_60d_percentile"]
            + self.stock_data["return_252d_percentile"]
        ) / 4

        print("Data loaded successfully.")
        print(f"Stock data shape: {self.stock_data.shape}")
        print(f"Benchmark data shape: {self.benchmark_data.shape}")
        print("Sample stock data:")
        print(self.stock_data.head())
        print("Sample benchmark return_5d:")
        print(self.benchmark_data.loc[self.benchmark_symbol, "return_5d"])
        print("sample etf data:")
        print(self.etf_data.head())
        print("Sample stock columns:")
        print(self.stock_data.columns.to_list())

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError()
        if col not in self.stock_data.columns:
            raise ValueError()
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str):
        return MomentumSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            return_5d=self.get(symbol, "return_5d"),
            return_20d=self.get(symbol, "return_20d"),
            return_60d=self.get(symbol, "return_60d"),
            return_252d=self.get(symbol, "return_252d"),
            momentum_composite_percentile=self.get(
                symbol, "momentum_composite_percentile"
            ),
            momentum_consistency=sum(
                [
                    self.get(symbol, "return_5d") > 0,
                    self.get(symbol, "return_20d") > 0,
                    self.get(symbol, "return_60d") > 0,
                    self.get(symbol, "return_252d") > 0,
                ]
            ),
            excess_return_5d=self.get(symbol, "excess_return_5d"),
            excess_return_20d=self.get(symbol, "excess_return_20d"),
            sector_relative_5d=self.get(symbol, "sector_relative_5d"),
            sector_relative_20d=self.get(symbol, "sector_relative_20d"),
            sector=self.get(symbol, "sector"),
            price=self.get(symbol, "close"),
            above_sma_200=self.get(symbol, "above_sma_200"),
            pct_from_52w_high=self.get(symbol, "pct_from_52w_high"),
            new_52w_high=self.get(symbol, "new_52w_high"),
            r_squared_60d=self.get(symbol, "r_squared_60d"),
            trend_slope_60d=self.get(symbol, "trend_slope_60d"),
            slope_x_r2=self.get(symbol, "slope_x_r2"),
            drawdown_from_recent_high=self.get(symbol, "drawdown_from_recent_high"),
            momentum_accel_20_60=self.get(symbol, "momentum_accel_20_60"),
            momentum_accel_5_20=self.get(symbol, "momentum_accel_5_20"),
            volume_ratio=self.get(symbol, "volume_ratio"),
            dollar_volume_20d_avg=self.get(symbol, "dollar_volume_20d_avg"),
            volatility_20=self.get(symbol, "volatility_20"),
            atr_pct=self.get(symbol, "atr_pct"),
            vol_adjusted_momentum=self.get(symbol, "vol_adjusted_momentum"),
            return_5d_percentile=self.get(symbol, "return_5d_percentile"),
            return_20d_percentile=self.get(symbol, "return_20d_percentile"),
            return_60d_percentile=self.get(symbol, "return_60d_percentile"),
            return_252d_percentile=self.get(symbol, "return_252d_percentile"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    etf_symbol = [
        "XLK",
        "XLY",
        "XLC",
        "XLF",
        "XLV",
        "XLI",
        "XLE",
        "XLB",
        "XLRE",
        "XLU",
        "XLP",
    ]
    benchmark = "SPY"
    signal_day = pd.Timestamp.today()
    print(signal_day)

    agent = MomentumFactorsModel(signal_day, symbols, benchmark, etf_symbol)
    for i in range(len(symbols)):
        Snapshot= agent.build_snapshot(symbols[i])
        print(Snapshot.to_agent_prompt()+"\n\n")
    print(agent.get("NVDA", "return_5d"))
