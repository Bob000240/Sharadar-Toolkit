import database.indicator_repository as indicator_repo
import database.descriptors_repository as sector_repo
import database.market_repository as market_repo

import pandas as pd
from dataclasses import dataclass

@dataclass
class MomentumSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp

    # Absolute momentum
    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float

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
    above_sma_50: bool
    pct_from_52w_high: float
    new_52w_high: bool

    # Trend quality
    r_squared_60d: float
    # R² of price vs time regression (0–1)

    trend_slope_60d: float
    # Annualized regression slope over 60d

    slope_x_r2: float
    # trend_slope_60d * r_squared_60d

    # Momentum acceleration
    momentum_accel_20_60: float
    # return_20d - return_60d

    momentum_accel_5_20: float
    # return_5d - return_20d

    # Volume / participation
    volume_ratio: float
    # current volume / 50d avg volume

    dollar_volume_20d_avg: float

    # Risk-adjusted momentum
    vol_adjusted_momentum: float
    # return_60d / volatility_20

    # Universe-relative ranks (0–100)
    return_5d_percentile: float
    return_20d_percentile: float
    return_60d_percentile: float
    return_252d_percentile: float
    
    report_sections : list[str]

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    def _fmt_header(self) -> str:
        return (
            f"[MOMENTUM] {self.symbol} | {str(self.signal_day)[:10]} | Sector: {self.sector} | Price: ${self.price:.2f}\n"
            f"Consistency: {self.momentum_consistency}/4 periods positive (5d/20d/60d/252d)"
        )

    def _fmt_absolute_momentum(self) -> str:
        return (
            "Absolute returns (universe rank):\n"
            f"  5d: {self._pct(self.return_5d)} (rank {self.return_5d_percentile:.0f}th) | "
            f"20d: {self._pct(self.return_20d)} (rank {self.return_20d_percentile:.0f}th) | "
            f"60d: {self._pct(self.return_60d)} (rank {self.return_60d_percentile:.0f}th) | "
            f"252d: {self._pct(self.return_252d)} (rank {self.return_252d_percentile:.0f}th)"
        )

    def _fmt_benchmark_relative(self) -> str:
        return (
            "vs S&P 500 (positive = outperforming):\n"
            f"  5d excess: {self._pct(self.excess_return_5d)} | "
            f"20d excess: {self._pct(self.excess_return_20d)}"
        )

    def _fmt_sector_relative(self) -> str:
        return (
            f"vs Sector ETF (positive = outperforming sector peers):\n"
            f"  5d vs sector: {self._pct(self.sector_relative_5d)} | "
            f"20d vs sector: {self._pct(self.sector_relative_20d)}"
        )

    def _fmt_trend_structure(self) -> str:
        high_note = "at new 52w high" if self.new_52w_high else f"{self._pct(self.pct_from_52w_high)} from 52w high"
        return (
            "Trend structure:\n"
            f"  Above SMA-200: {self.above_sma_200} | Above SMA-50: {self.above_sma_50} | {high_note}\n"
            f"  60d R²: {self.r_squared_60d:.2f} (0=chaotic, 1=linear) | "
            f"Trend slope: {self._pct(self.trend_slope_60d)}/yr | "
            f"Trend quality (slope×R²): {self.slope_x_r2:.3f}"
        )

    def _fmt_momentum_acceleration(self) -> str:
        return (
            "Momentum acceleration (positive = accelerating):\n"
            f"  Short-term (5d vs 20d): {self._pct(self.momentum_accel_5_20)} | "
            f"Medium-term (20d vs 60d): {self._pct(self.momentum_accel_20_60)}"
        )

    def _fmt_volume_liquidity(self) -> str:
        return (
            "Volume & liquidity:\n"
            f"  Volume ratio: {self.volume_ratio:.2f}x vs 50d avg (>1 = above-average participation) | "
            f"Avg daily dollar vol: ${self.dollar_volume_20d_avg:,.0f}"
        )

    def _fmt_risk_volatility(self) -> str:
        return (
            "Risk-adjusted momentum:\n"
            f"  Vol-adjusted (60d return / 20d vol): {self.vol_adjusted_momentum:.2f}"
        )

    def to_agent_prompt(self) -> str:
        prompt_sections = {
            "absolute_momentum": self._fmt_absolute_momentum(),
            "benchmark_relative": self._fmt_benchmark_relative(),
            "sector_relative": self._fmt_sector_relative(),
            "trend_structure": self._fmt_trend_structure(),
            "momentum_acceleration": self._fmt_momentum_acceleration(),
            "volume_liquidity": self._fmt_volume_liquidity(),
            "risk_volatility": self._fmt_risk_volatility(),
        }

        try:
            return "\n\n".join([
                self._fmt_header(),
                *(prompt_sections[section] for section in self.report_sections if section in prompt_sections)
            ])
        except Exception as e:
            print(f"Error building prompt: {e}")
            print("Falling back to full report.")
            return "\n\n".join([
                self._fmt_header(),
                self._fmt_absolute_momentum(),
                self._fmt_benchmark_relative(),
                self._fmt_sector_relative(),
                self._fmt_trend_structure(),
                self._fmt_momentum_acceleration(),
                self._fmt_volume_liquidity(),
                self._fmt_risk_volatility(),
            ])


class MomentumFactorsModel:
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
        all_indicators["above_sma_50"]  = all_indicators["close"] > all_indicators["sma_50"]
        all_indicators["above_sma_200"] = all_indicators["close"] > all_indicators["sma_200"]

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

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError()
        if col not in self.stock_data.columns:
            raise ValueError()
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str, report_sections: list[str] | str) -> MomentumSnapshot:
        return MomentumSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            return_5d=self.get(symbol, "return_5d"),
            return_20d=self.get(symbol, "return_20d"),
            return_60d=self.get(symbol, "return_60d"),
            return_252d=self.get(symbol, "return_252d"),
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
            report_sections=report_sections if isinstance(report_sections, list) else [report_sections],

        )


if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA", "AVGO", "AMD",
    "ADBE", "CSCO", "ORCL", "CRM", "INTC"]
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
    report_sections = [
        "absolute_momentum",
        "benchmark_relative",
        "risk_volatility",
    ]
    for i in range(len(symbols)):
        Snapshot= agent.build_snapshot(symbols[i], report_sections)
        print(Snapshot.to_agent_prompt()+"\n\n")
