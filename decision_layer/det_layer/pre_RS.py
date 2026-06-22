import re
import pandas as pd
from decision_layer.det_layer.pre_filter import SignalAgent, AgentVerdict
from decision_layer.agentic_layer.llm_client import call_llm_analyze, REMOTE_MODEL
import data_det.signals.sig_momentum as sig_mom
from set_up.config import STOCK_SYMBOLS, BENCHMARK_SYMBOLS

_DIR_MAP = {"BUY": "bullish", "WAIT": "neutral", "AVOID": "bearish"}

MOMENTUM_SECTIONS = [
    "trend_structure",
    "absolute_momentum",
    "benchmark_relative",
    "momentum_acceleration",
    "oscillators",
    "breakout_pullback",
    "ema_crossover",
    "volume_liquidity",
]

_BENCHMARK = "SPY"
_ETFS = [s for s in BENCHMARK_SYMBOLS if s != "SPY"]
_STRATEGY = "Relative Strength Momentum"

class RSMomentumAgent(SignalAgent):
    def __init__(self, analysis_model: str = REMOTE_MODEL):
        super().__init__(analysis_model)
        self.signal_day = pd.Timestamp.today()
        self._mom_model = sig_mom.MomentumFactorsModel(self.signal_day, STOCK_SYMBOLS, _BENCHMARK, _ETFS)
        self.stock_data = self._mom_model.stock_data.copy()
        self.analysis_model = analysis_model
        self.stock_data["_cs_return_12_1"] = (
            (1 + self.stock_data["return_252d"]) / (1 + self.stock_data["return_20d"]) - 1
        )
        self.stock_data["_cs_rank"] = self.stock_data["_cs_return_12_1"].rank(pct=True)
        self.strategy = _STRATEGY
        self.system_prompt = _SYSTEM_PROMPT

    def pre_filter(
        self,
        top_cs_pct: float = 0.30,
        min_rs_percentile: float = 75,
        min_r_squared: float = 0.65,
        max_per_sector: int = 3,
    ) -> list[str]:
        df = self.stock_data.copy()

        # Gate 0: Cross-sectional momentum rank
        cs_pass = df["_cs_rank"] >= (1.0 - top_cs_pct)

        # Gate 1: Short-term RS
        rs_pass = (
            (df["return_20d_percentile"] > min_rs_percentile) &
            (df["excess_return_20d"] > 0) &
            (df["sector_relative_20d"] > 0)
        )

        # Gate 2: Trend health
        trend_pass = (
            df["above_sma_200"] &
            df["above_sma_50"] &
            (df["r_squared_60d"] > min_r_squared) &
            (df["slope_x_r2"] > 0)
        )

        # Gate 3: Entry signal (OR logic)
        breakout_pass = (
            (df["price_vs_20d_high"] > -0.03) &
            (df["volume_ratio"] > 1.5)
        )
        pullback_pass = (
            (df["pct_from_sma_20"] > -0.05) &
            (df["pct_from_sma_20"] < 0.03) &
            (df["consolidation_tightness"] < 0.7)
        )
        crossover_pass = (
            (df["macd_hist"] > 0) &
            (df["momentum_accel_5_20"] > 0)
        )
        entry_pass = breakout_pass | pullback_pass | crossover_pass

        passed = df[cs_pass & rs_pass & trend_pass & entry_pass]
        passed = passed.sort_values("_cs_rank", ascending=False)
        if max_per_sector:
            passed = passed.groupby("sector").head(max_per_sector)
        return passed.index.tolist()

    def _detect_entry_modes(self, symbol: str) -> list[str]:
        row = self.stock_data.loc[symbol]
        modes = []
        if row["price_vs_20d_high"] > -0.03 and row["volume_ratio"] > 1.5:
            modes.append("breakout")
        if row["pct_from_sma_20"] > -0.05 and row["pct_from_sma_20"] < 0.03 and row["consolidation_tightness"] < 0.7:
            modes.append("pullback")
        if row["macd_hist"] > 0 and row["momentum_accel_5_20"] > 0:
            modes.append("crossover")
        return modes

    def exit_signals(self, symbol: str) -> dict:
        row = self.stock_data.loc[symbol]
        price = float(row["close"])
        atr = float(row["atr_14"])
        stop_dist = 2 * atr

        modes = self._detect_entry_modes(symbol)
        primary_mode = modes[0] if modes else "breakout"
        max_hold_days = {"breakout": 20, "pullback": 10, "crossover": 15}.get(primary_mode, 20)

        return {
            "stop_price":    round(price - stop_dist, 2),
            "stop_pct":      round(-stop_dist / price * 100, 2),
            "target_price":  round(price + 3 * stop_dist, 2),
            "target_pct":    round(3 * stop_dist / price * 100, 2),
            "atr":           round(atr, 4),
            "max_hold_days": max_hold_days,
        }

    def run(self, symbol: str) -> AgentVerdict:
        active_modes = self._detect_entry_modes(symbol)
        snapshot = self._mom_model.build_snapshot(symbol, MOMENTUM_SECTIONS)
        thesis = self.analyze(snapshot, active_modes)
        direction, confidence = self._parse_output_block(thesis)
        exit_signals = self.exit_signals(symbol)
        return AgentVerdict(
            symbol=symbol,
            strategy=self.strategy,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
            sector=str(self.stock_data.loc[symbol, "sector"]),
            stop_price=exit_signals["stop_price"],
            stop_pct=exit_signals["stop_pct"],
            target_price=exit_signals["target_price"],
            target_pct=exit_signals["target_pct"],
            atr=exit_signals["atr"],
            max_hold_days=exit_signals["max_hold_days"],
        )


if __name__ == "__main__":
    agent = RSMomentumAgent("qwen3:14b")
    candidates = agent.pre_filter()
    print("Candidates:", candidates)
    for symbol in candidates:
        verdict = agent.run(symbol)
        print(verdict)
