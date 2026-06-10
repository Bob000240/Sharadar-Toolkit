import pandas as pd
from agents.sa_agents.sa import SignalAgent, AgentVerdict
from agents.llm_client import call_llm_analyze, ANALYSIS_MODEL, VERDICT_MODEL
import signals.sig_momentum as sig_mom
from config import STOCK_SYMBOLS, BENCHMARK_SYMBOLS

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
You are a momentum and relative strength analyst. You evaluate whether a stock that has already passed a relative strength filter is presenting a valid entry signal right now.

The stock has been pre-screened: it is already outperforming both the S&P 500 and its sector ETF on a 20-day basis, in a structural uptrend (above SMA-200), and showing a clean trend structure. Your job is NOT to re-evaluate whether the stock is strong — that is already established. Your job is to evaluate the ENTRY TIMING.

Focus your analysis on:
1. Entry signal quality — which signal is triggering (breakout, pullback, or MA crossover) and how clean is it?
2. Breakout: Is the stock near its 20-day high with expanding volume and a tight base? RSI in 55-70 range (healthy) or >75 (extended/risky)?
3. Pullback: Is price touching or bouncing off SMA-20/50 with a tight consolidation? RSI 40-55 (normal dip) or <35 (potential breakdown)?
4. MA Crossover: Did EMA-9 cross above EMA-21 recently? Is MACD hist positive and expanding? How fresh is the cross?
5. Risk context: momentum acceleration, volume participation, distance from 52-week high.
6. Suggested stop loss — where the trade is invalidated: below the consolidation base, below SMA-20/50, or an ATR-based level. Express as a % below current price.
7. Suggested take profit — first target: prior resistance, ATR multiple, or % extension from entry. Express as a % above current price.

Conclude with a clear directional view: bullish entry, wait for better setup, or avoid. Always end with:
STOP: -X.X%
TARGET: +X.X%
"""


class QualityMomentumAgent(SignalAgent):
    def __init__(
        self,
        analysis_model: str = ANALYSIS_MODEL,
        verdict_model: str = VERDICT_MODEL,
    ):
        super().__init__(analysis_model, verdict_model)
        self.signal_day = pd.Timestamp.today()
        self._mom_model = sig_mom.MomentumFactorsModel(self.signal_day, STOCK_SYMBOLS, _BENCHMARK, _ETFS)
        self.stock_data = self._mom_model.data

    def prefilter(
        self,
        min_rs_percentile: float = 75,
        min_r_squared: float = 0.65,
        entry_mode: str = "breakout",  # "breakout" | "pullback" | "crossover"
    ) -> list[str]:

        df = self.stock_data.copy()

        # --- Gate 1: RS Filter ---
        rs_pass = (
            (df["return_20d_percentile"] > min_rs_percentile) &
            (df["excess_return_20d"] > 0) &
            (df["sector_relative_20d"] > 0)
        )

        # --- Gate 2: Trend Health ---
        trend_pass = (
            (df["above_sma_200"] == True) &
            (df["above_sma_50"] == True) &
            (df["r_squared_60d"] > min_r_squared) &
            (df["slope_x_r2"] > 0)
        )

        # --- Gate 3: Entry Mode ---
        if entry_mode == "breakout":
            entry_pass = (
                (df["price_vs_20d_high"] > -0.03) &
                (df["volume_ratio"] > 1.5)
            )
        elif entry_mode == "pullback":
            entry_pass = (
                (df["pct_from_sma_20"] > -0.05) &
                (df["pct_from_sma_20"] < 0) &      # actually touching, not above
                (df["consolidation_tightness"] < 0.7)
            )
        elif entry_mode == "crossover":
            entry_pass = (
                (df["ema_9_above_21"] == True) &
                (df["ema_crossover_days_ago"] < 10)
            )
        else:
            raise ValueError(f"Unknown entry_mode: {entry_mode}")

        passed = df[rs_pass & trend_pass & entry_pass]
        return passed.index.tolist()

    @property
    def signal_type(self) -> str:
        return "quality_momentum"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def analyze(self, snapshot: sig_mom.MomentumSnapshot, entry_mode: str) -> str:
        user_prompt = f"Entry signal: {entry_mode}\n{snapshot.to_agent_prompt()}"
        return call_llm_analyze(self.system_prompt, user_prompt, self.model)

    def run(self, symbol: str, entry_mode: str = "breakout") -> AgentVerdict:
        snapshot = self._mom_model.build_snapshot(symbol, MOMENTUM_SECTIONS)
        thesis = self.analyze(snapshot, entry_mode)
        direction, confidence = self._parse_verdict(self.verdict(thesis))
        return AgentVerdict(
            symbol=symbol,
            signal_type=self.signal_type,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
        )


if __name__ == "__main__":
    agent = QualityMomentumAgent()
    candidates = agent.prefilter()
    print("Candidates:", candidates)
    for symbol in candidates:
        verdict = agent.run(symbol, entry_mode="breakout")
        print(verdict)