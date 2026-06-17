import database.descriptors_repository as descriptor_repo
import database.market_repository as market_repo
from raw_data.market_data import MarketData
from processed_data.indicators import compute_indicators

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

    # Breakout signals
    price_vs_20d_high: float        # % from 20-day high (0 = at high = breakout zone)
    consolidation_tightness: float  # stddev of last 10 days / ATR — low = tight base

    # Pullback signals
    pct_from_sma_20: float          # how close price is to 20 SMA
    pct_from_sma_50: float          # how close price is to 50 SMA

    # MA Crossover signals
    ema_9: float
    ema_21: float
    ema_9_above_21: bool            # crossover state
    ema_crossover_days_ago: int     # freshness of the cross

    # Oscillators
    rsi_14: float
    macd_hist: float                # positive = bullish momentum, negative = bearish

    report_sections: list[str]

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
            f"  60d R^2: {self.r_squared_60d:.2f} (0=chaotic, 1=linear) | "
            f"Trend slope: {self._pct(self.trend_slope_60d)}/yr | "
            f"Trend quality (slope*R^2): {self.slope_x_r2:.3f}"
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

    def _fmt_oscillators(self) -> str:
        rsi_note = "overbought" if self.rsi_14 > 70 else "oversold" if self.rsi_14 < 30 else "neutral"
        macd_note = "bullish" if self.macd_hist > 0 else "bearish"
        return (
            "Oscillators:\n"
            f"  RSI-14: {self.rsi_14:.1f} ({rsi_note}) | "
            f"MACD hist: {self.macd_hist:.4f} ({macd_note})"
        )

    def _fmt_breakout_pullback(self) -> str:
        return (
            "Breakout & pullback signals:\n"
            f"  From 20d high: {self._pct(self.price_vs_20d_high)} (0 = at high = breakout zone) | "
            f"Consolidation tightness: {self.consolidation_tightness:.2f} (low = tight base)\n"
            f"  From SMA-20: {self._pct(self.pct_from_sma_20)} | From SMA-50: {self._pct(self.pct_from_sma_50)}"
        )

    def _fmt_ema_crossover(self) -> str:
        cross_str = f"{int(self.ema_crossover_days_ago)}d ago" if self.ema_crossover_days_ago is not None else "N/A"
        return (
            "EMA crossover (9/21):\n"
            f"  EMA-9: {self.ema_9:.2f} | EMA-21: {self.ema_21:.2f} | "
            f"9 above 21: {self.ema_9_above_21} | Last cross: {cross_str}"
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
            "oscillators": self._fmt_oscillators(),
            "breakout_pullback": self._fmt_breakout_pullback(),
            "ema_crossover": self._fmt_ema_crossover(),
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
                self._fmt_oscillators(),
                self._fmt_breakout_pullback(),
                self._fmt_ema_crossover(),
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
        lookback_start = self.signal_day - pd.Timedelta(days=400)
        yesterday = self.signal_day - pd.Timedelta(days=1)

        ohlcv = market_repo.get_OHLCV(self.all_symbols, lookback_start, yesterday)
        ohlcv["date"] = pd.to_datetime(ohlcv["date"])

        live = MarketData().get_live_snapshot(self.all_symbols)
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

        sector_mapping = descriptor_repo.get_descriptors(self.all_symbols)[["symbol", "sector"]].set_index("symbol")

        all_indicators = pd.DataFrame(rows).set_index("symbol")
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
        
