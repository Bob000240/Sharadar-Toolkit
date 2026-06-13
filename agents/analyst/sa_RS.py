import re
import pandas as pd
from agents.analyst.sa import SignalAgent, AgentVerdict
from agents.llm_client import call_llm_analyze, ANALYSIS_MODEL
import signals.sig_momentum as sig_mom
from config import STOCK_SYMBOLS, BENCHMARK_SYMBOLS

_DIR_MAP = {"BUY": "bullish", "WAIT": "neutral", "AVOID": "bearish"}

MOMENTUM_SECTIONS = [
    "trend_structure",
    "absolute_momentum",
    "benchmark_relative",
    "oscillators",
    "breakout_pullback",
    "ema_crossover",
    "volume_liquidity",
]

_BENCHMARK = "SPY"
_ETFS = [s for s in BENCHMARK_SYMBOLS if s != "SPY"]

_SYSTEM_PROMPT = """
You are SA-RS (Relative Strength Momentum), a strategy agent evaluating entry timing for pre-qualified candidates.

CONTEXT - WHAT IS ALREADY ESTABLISHED:
The stock has passed all four prefilter gates:
- Gate 0 CS Rank: top 30% of universe by 12-1 month cross-sectional momentum (medium-term systematic rank)
- Gate 1 RS: return_20d_percentile > 75th, outperforming SPY and sector ETF on 20d basis
- Gate 2 Trend: above SMA-200 and SMA-50, r_squared_60d > 0.65, slope_x_r2 > 0
- Gate 3 Entry: at least one of the following signals fired (active signals listed in user message):
    * Breakout: price within 3% of 20d high, volume_ratio > 1.5
    * Pullback: tight consolidation, price within -5% to +3% of SMA-20
    * Crossover: MACD histogram positive AND 5d momentum > 20d momentum (short-term acceleration)

DO NOT re-evaluate Gates 0–2. They are established facts. Your job is to assess entry quality for the active signal(s). If multiple signals are active, treat the confluence as a positive factor and reflect it in your confidence score.

YOUR RESPONSIBILITIES:
1. Entry signal quality — does the overall picture support the declared signal(s)?
2. Signal conflicts — are any indicators contradicting the entry?
3. Confidence — your self-assessed conviction in this specific entry, 0.0–1.0.
   - >0.75: clean setup, no conflicts, volume confirming
   - 0.50–0.75: valid setup with at least one moderate concern
   - <0.50: conflicting signals or setup quality too low

ENTRY MODE EVALUATION CRITERIA:

BREAKOUT:
- Price within 3% of 20d high with volume_ratio > 1.5 ✓ (already gated)
- Assess: how tight is the base? (consolidation_tightness)
- Assess: RSI health — 55-70 is ideal, >75 is extended/risky
- Assess: is momentum accelerating? (momentum_accel_5_20 > 0)
- Conflict signals: MACD hist negative, volume_ratio declining, momentum_accel negative
- NOTE: being above SMA-20 is EXPECTED for a breakout — do not flag it as a concern unless pct_from_sma_20 > 0.12 (extreme extension)

PULLBACK:
- Price near SMA-20 with tight consolidation ✓ (already gated)
- Assess: RSI zone - 40-55 is healthy dip, <35 risks breakdown
- Assess: is the pullback orderly? (consolidation_tightness, r_squared_60d)
- Assess: sector and benchmark holding up? (sector_relative_20d trend)
- Conflict signals: accelerating momentum deceleration, volume expanding on the dip

CROSSOVER (momentum re-ignition):
- MACD hist positive and 5d return > 20d return ✓ (already gated)
- Assess: MACD hist magnitude - larger positive = stronger re-ignition
- Assess: how fresh is the acceleration? (momentum_accel_5_20 magnitude)
- Assess: volume confirming the acceleration
- Conflict signals: RSI already overbought >75, price extended from SMA-50, MACD hist shrinking

RESPONSE FORMAT:
First, write 3-5 sentences of analysis. You must explicitly reference:
- Which signal(s) fired and whether the data supports them
- RSI zone and what it implies for this setup
- Whether volume, MACD, and momentum acceleration are confirming or conflicting
- Any single factor that most limits your confidence

Then end with this exact block:

DIRECTION: [BUY|WAIT|AVOID]
CONFIDENCE: [0.00-1.00]
SIGNAL_QUALITY: [CLEAN|VALID|CONFLICTED]
PRIMARY_CONCERN: [one sentence identifying a genuine conflict — or NONE if there are no real concerns. Do not invent a concern to fill this field.]

Confidence calibration:
- 0.80+: all key indicators confirming, no conflicts, tight base
- 0.65-0.79: setup is valid but at least one indicator is not confirming
- 0.50-0.64: mixed signals, real concerns present
- <0.50: more against than for — use WAIT or AVOID
"""


class RSMomentumAgent(SignalAgent):
    def __init__(self, analysis_model: str = ANALYSIS_MODEL):
        super().__init__(analysis_model)
        self.signal_day = pd.Timestamp.today()
        self._mom_model = sig_mom.MomentumFactorsModel(self.signal_day, STOCK_SYMBOLS, _BENCHMARK, _ETFS)
        self.stock_data = self._mom_model.data.copy()

        # Cross-sectional 12-1 month return rank — computed once at init
        # Skip the last month (return_20d) to avoid short-term reversal
        self.stock_data["_cs_return_12_1"] = (
            (1 + self.stock_data["return_252d"]) / (1 + self.stock_data["return_20d"]) - 1
        )
        self.stock_data["_cs_rank"] = self.stock_data["_cs_return_12_1"].rank(pct=True)

    def prefilter(
        self,
        top_cs_pct: float = 0.30,
        min_rs_percentile: float = 75,
        min_r_squared: float = 0.65,
        max_per_sector: int = 3,
    ) -> list[str]:
        df = self.stock_data.copy()

        # --- Gate 0: Cross-sectional momentum rank (quant layer) ---
        cs_pass = df["_cs_rank"] >= (1.0 - top_cs_pct)

        # --- Gate 1: Short-term RS ---
        rs_pass = (
            (df["return_20d_percentile"] > min_rs_percentile) &
            (df["excess_return_20d"] > 0) &
            (df["sector_relative_20d"] > 0)
        )

        # --- Gate 2: Trend health ---
        trend_pass = (
            (df["above_sma_200"] == True) &
            (df["above_sma_50"] == True) &
            (df["r_squared_60d"] > min_r_squared) &
            (df["slope_x_r2"] > 0)
        )

        # --- Gate 3: Entry signal (OR logic — at least one must fire) ---
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

    @property
    def signal_type(self) -> str:
        return "Relative Strength Momentum"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def _compute_risk(self, symbol: str) -> dict:
        row = self.stock_data.loc[symbol]
        price = float(row["close"])
        atr = float(row["atr_14"])
        stop_dist = 2 * atr
        return {
            "stop_price":   round(price - stop_dist, 2),
            "stop_pct":     round(-stop_dist / price * 100, 2),
            "target_price": round(price + 3 * stop_dist, 2),
            "target_pct":   round(3 * stop_dist / price * 100, 2),
            "atr":          round(atr, 4),
        }

    def _compute_flags(self, symbol: str) -> dict:
        row = self.stock_data.loc[symbol]
        rsi = float(row["rsi_14"])
        return {
            "rsi":                   round(rsi, 1),
            "rsi_zone":              ("overbought" if rsi > 75 else "healthy" if rsi >= 55 else "pullback_zone" if rsi >= 40 else "oversold"),
            "macd_confirming":       bool(row["macd_hist"] > 0),
            "volume_confirming":     bool(row["volume_ratio"] > 1.5),
            "momentum_accelerating": bool(row["momentum_accel_5_20"] > 0),
            "base_tight":            bool(row["consolidation_tightness"] < 0.7),
        }

    def analyze(self, snapshot, active_modes: list[str]) -> str:
        modes_str = " + ".join(active_modes) if active_modes else "none"
        user_prompt = f"Active entry signals: {modes_str}\n\n{snapshot.to_agent_prompt()}"
        return call_llm_analyze(self.system_prompt, user_prompt, self.model)

    def _parse_output_block(self, thesis: str) -> tuple[str, float]:
        dir_match = re.search(r"DIRECTION:\s*(BUY|WAIT|AVOID)", thesis)
        conf_match = re.search(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", thesis)
        direction = _DIR_MAP.get(dir_match.group(1), "neutral") if dir_match else "neutral"
        confidence = max(0.0, min(1.0, float(conf_match.group(1)))) if conf_match else 0.5
        return direction, confidence

    def run(self, symbol: str) -> AgentVerdict:
        active_modes = self._detect_entry_modes(symbol)
        snapshot = self._mom_model.build_snapshot(symbol, MOMENTUM_SECTIONS)
        thesis = self.analyze(snapshot, active_modes)
        direction, confidence = self._parse_output_block(thesis)
        return AgentVerdict(
            symbol=symbol,
            signal_type=self.signal_type,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
        )


if __name__ == "__main__":
    agent = RSMomentumAgent()
    candidates = agent.prefilter()
    print("Candidates:", candidates)
    for symbol in candidates:
        verdict = agent.run(symbol)
        print(verdict)
