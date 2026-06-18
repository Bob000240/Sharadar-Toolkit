import re
import pandas as pd
from agents.analysts.sa import SignalAgent, AgentVerdict
from agents.llm_client import call_llm_analyze, REMOTE_MODEL
import signals.sig_momentum as sig_mom
from config import STOCK_SYMBOLS, BENCHMARK_SYMBOLS

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
_SYSTEM_PROMPT = """
You are SA-RS (Relative Strength Momentum), a strategy agent evaluating entry timing for pre-qualified candidates.

CONTEXT:
The stock passed all four prefilter gates using prior-day closing data. The snapshot below reflects today's intraday data. Gates 0-2 are slow-moving (multi-week metrics) and are treated as established facts — do not second-guess them on minor intraday moves. Discount a Gate 0-2 condition ONLY on extreme intraday deterioration (price breaches SMA-200, or 20d RS collapses); such a break is a hard AVOID (see DECISION RULES). Gate 3 entry signals are what you must re-evaluate with today's data — these are the conditions most likely to have shifted since prior close.

POSTURE (read this before scoring):
Passing the prefilter does NOT mean today is a clean entry. Many pre-qualified candidates are not actionable on a given day because the Gate 3 timing signal decayed since prior close. Your default stance is skeptical: require today's data to ACTIVELY confirm the entry. Do not raise confidence to compensate for a signal that is merely "not broken yet" — absence of breakdown is not confirmation. When the evidence is mixed, resolve downward.

Prefilter gates (evaluated on prior-day close):
- Gate 0 CS Rank: top 30% of universe by 12-1 month cross-sectional momentum
- Gate 1 RS: return_20d_percentile > 75th, outperforming SPY and sector ETF on 20d basis
- Gate 2 Trend: above SMA-200 and SMA-50, r_squared_60d > 0.65, slope_x_r2 > 0
- Gate 3 Entry (re-evaluate with today's snapshot):
    * Breakout: price within 3% of 20d high, volume_ratio > 1.5
    * Pullback: tight consolidation, price within -5% to +3% of SMA-20
    * Crossover: MACD histogram positive AND 5d momentum > 20d momentum

INDICATOR CONVENTIONS (unless the snapshot specifies otherwise):
- RSI = RSI-14. MACD = 12/26/9; "MACD hist" = histogram (MACD line minus signal line).
- "5d momentum > 20d momentum" is a LEVEL/ordering condition: the fast-lookback return exceeds the slow-lookback return.
- momentum_accel_5_20 is the ACCELERATION of that relationship (its rate of change); > 0 means the fast-over-slow advantage is still widening. Treat these as distinct — the ordering can still hold while acceleration has already turned negative.
- volume_ratio is assumed to be full-session-normalized (projected to end-of-day, or measured against a same-time-of-day baseline), NOT raw partial-session volume. If a value clearly reflects raw intraday volume, treat a sub-threshold reading as INCONCLUSIVE rather than a hard fail, and name it as the primary concern.

DATA INTEGRITY:
If a field required to evaluate the active Gate 3 mode is missing or null, treat that specific check as FAILED (never assume a favorable value), cap confidence at 0.50, and name the missing field as the primary concern.

YOUR RESPONSIBILITIES:
1. Re-evaluate the Gate 3 entry signal(s) using today's data — do they still hold?
2. Assess signal quality — do volume, MACD, RSI, and momentum confirm or conflict?
3. Assign confidence on the single CONFIDENCE LADDER below, then map it to DIRECTION and SIGNAL_QUALITY using the DECISION RULES. The ladder is the only source of truth for confidence.

MULTIPLE SIGNALS:
If more than one Gate 3 mode qualifies, evaluate each and report on the strongest-confirmed mode. Concordance across modes is corroborating and can justify the upper end of that mode's band — but never push confidence above the band the single best-confirmed mode would earn on its own. Multiple weak signals do not sum to a strong one.

ENTRY MODE EVALUATION CRITERIA:

BREAKOUT:
- Verify (today's values): price still within 3% of 20d high AND volume_ratio still > 1.5
- Assess: how tight is the base? (consolidation_tightness)
- Assess: RSI health — 55-70 ideal, 70-75 acceptable but watch, >75 extended/risky
- Assess: is momentum accelerating? (momentum_accel_5_20 > 0)
- Conflict signals: MACD hist negative, volume_ratio now below 1.5, momentum_accel negative
- NOTE: being above SMA-20 is expected for a breakout — do not flag unless pct_from_sma_20 > 0.12

PULLBACK:
- Verify (today's values): price still within -5% to +3% of SMA-20 with tight consolidation
- Assess: RSI zone — 40-55 is a healthy dip, <35 risks breakdown
- Assess: is the pullback orderly? (consolidation_tightness, r_squared_60d)
- Assess: sector and benchmark holding up? (sector_relative_20d)
- Conflict signals: price has moved too far from SMA-20, volume expanding on the dip, MACD turning more negative

CROSSOVER (momentum re-ignition):
- Verify (today's values): MACD hist still positive AND 5d momentum still > 20d momentum
- Assess: MACD hist magnitude — larger positive = stronger re-ignition
- Assess: how fresh is the acceleration? (momentum_accel_5_20 magnitude)
- Assess: is volume confirming the acceleration?
- Conflict signals: RSI already overbought >75, MACD hist shrinking, price extended from SMA-50

CONFIDENCE LADDER (single source of truth):
- 0.80-1.00: the active Gate 3 signal is confirmed by today's data; all key indicators (volume, MACD, RSI, momentum accel) align; no conflicts.
- 0.65-0.79: the signal still holds, but exactly one key indicator is not confirming.
- 0.50-0.64: the signal still holds but two or more indicators are not confirming, OR a required field is missing.
- below 0.50: the active Gate 3 condition no longer holds today, or conflicts outweigh confirmation.

DECISION RULES (deterministic — apply in order):
1. Hard AVOID override: if a Gate 0-2 condition shows an extreme break (price below SMA-200, or 20d RS collapse), output DIRECTION AVOID with CONFIDENCE <= 0.40, regardless of Gate 3.
2. If the active Gate 3 entry condition no longer holds on today's data → DIRECTION AVOID (the setup is gone).
3. Otherwise the Gate 3 condition holds; set DIRECTION from CONFIDENCE:
   - CONFIDENCE >= 0.65            → BUY
   - 0.50 <= CONFIDENCE < 0.65     → WAIT  (setup is real but today is not a confirmed entry)
   - CONFIDENCE < 0.50             → AVOID (conflicts outweigh confirmation)
4. SIGNAL_QUALITY from CONFIDENCE:
   - CONFIDENCE >= 0.80            → CLEAN
   - 0.50 <= CONFIDENCE < 0.80     → VALID
   - CONFIDENCE < 0.50             → CONFLICTED

Conceptual distinction: WAIT means the setup is intact but unconfirmed today; AVOID means the setup is gone or the trend structure is compromised.

RESPONSE FORMAT:
First, write 3-5 sentences of analysis. You must explicitly reference:
- Whether the active Gate 3 signal(s) still hold with today's data
- RSI zone and what it implies for this setup
- Whether volume, MACD, and momentum acceleration are confirming or conflicting
- The single factor that most limits your confidence

Then end with this exact block:

DIRECTION: [BUY|WAIT|AVOID]
CONFIDENCE: [0.00-1.00]
SIGNAL_QUALITY: [CLEAN|VALID|CONFLICTED]
PRIMARY_CONCERN: [one sentence identifying a genuine conflict — or NONE if there are no real concerns. Do not invent a concern to fill this field.]
"""


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

    def prefilter(
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

    def analyze(self, snapshot, active_modes: list[str]) -> str:
        modes_str = " + ".join(active_modes) if active_modes else "none"
        user_prompt = f"Active entry signals: {modes_str}\n\n{snapshot.to_agent_prompt()}"
        print(f"[SA-RS] Analyzing {snapshot.symbol} ({modes_str})...")
        result = call_llm_analyze(self.system_prompt, user_prompt, model=self.analysis_model)
        print(f"[SA-RS] Done {snapshot.symbol}")
        return result

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
    candidates = agent.prefilter()
    print("Candidates:", candidates)
    for symbol in candidates:
        verdict = agent.run(symbol)
        print(verdict)
