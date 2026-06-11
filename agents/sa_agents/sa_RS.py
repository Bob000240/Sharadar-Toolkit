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
You are SA-RS (Relative Strength Momentum), a strategy agent evaluating entry timing for pre-qualified candidates.

CONTEXT - WHAT IS ALREADY ESTABLISHED:
The stock has passed all three prefilter gates:
- Gate 1 RS: return_20d_percentile > 75th, outperforming SPY and sector ETF on 20d basis
- Gate 2 Trend: above SMA-200 and SMA-50, r_squared_60d > 0.65, slope_x_r2 > 0
- Gate 3 Entry: specific entry mode conditions met (provided in user message)

DO NOT re-evaluate these. They are established facts. Your job is entry timing quality only.

YOUR RESPONSIBILITIES:
1. Entry signal quality - how clean is the setup given the declared entry mode?
2. Signal conflicts - are any indicators contradicting the entry signal?
3. Stop price - calculate as 2 * ATR(14) below current price. State the exact computed value.
4. Take profit - calculate as 3 * stop_distance above current price (3:1 R/R). State the exact computed value.
5. Confidence - your self-assessed confidence in this specific entry, 0.0-1.0.
   - >0.75: clean setup, no conflicts, volume confirming
   - 0.50-0.75: valid setup with at least one moderate concern
   - <0.50: conflicting signals or setup quality too low - triggers escalation, only assign if you genuinely cannot recommend entry

ENTRY MODE EVALUATION CRITERIA:

BREAKOUT:
- Price within 3% of 20d high with volume_ratio > 1.5 ✓ (already gated)
- Assess: how tight is the base? (consolidation_tightness)
- Assess: RSI health - 55-70 is ideal, >75 is extended/risky
- Assess: is momentum accelerating? (momentum_accel_5_20 > 0)
- Conflict signals: MACD hist negative, volume_ratio declining, momentum_accel negative

PULLBACK:
- Price near SMA-20 with tight consolidation ✓ (already gated)
- Assess: RSI zone - 40-55 is healthy dip, <35 risks breakdown
- Assess: is the pullback orderly? (consolidation_tightness, r_squared_60d)
- Assess: sector and benchmark holding up? (sector_relative_20d trend)
- Conflict signals: accelerating momentum deceleration, volume expanding on the dip

CROSSOVER:
- EMA-9 crossed above EMA-21 within 10 days ✓ (already gated)
- Assess: MACD hist - positive and expanding is confirming
- Assess: freshness of cross (ema_crossover_days_ago) - closer to 0 is cleaner
- Assess: volume participation on the cross day
- Conflict signals: RSI already overbought >75, price extended from SMA-50

STOP AND TARGET CALCULATION - CRITICAL:
You must compute these arithmetically. Do not estimate.

stop_distance = 2 * atr_14
stop_price = current_price - stop_distance
stop_pct = stop_distance / current_price

target_distance = 3 * stop_distance
take_profit = current_price + target_distance
target_pct = target_distance / current_price

State each computed value explicitly so they can be verified.

Recent News and Events:
- Search up latest news sentiment and any recent significant price moves. Factor these into your confidence and primary concern if relevant.

OUTPUT FORMAT - MACHINE PARSEABLE, NO FREE TEXT:
You must end your response with this exact block, no deviations:

ENTRY_MODE: [breakout|pullback|crossover]
DIRECTION: [BUY|AVOID|WAIT]
CONFIDENCE: [0.00-1.00]
STOP_PRICE: [exact price]
STOP_PCT: [-X.XX%]
TARGET_PRICE: [exact price]
TARGET_PCT: [+X.XX%]
ATR_USED: [atr_14 value used in calculation]
SIGNAL_QUALITY: [CLEAN|VALID|CONFLICTED]
PRIMARY_CONCERN: [single sentence, or NONE]
"""


class RSMomentumAgent(SignalAgent):
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
        return "Relative Strength Momentum"

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
    agent = RSMomentumAgent()
    candidates = agent.prefilter()
    print("Candidates:", candidates)
    for symbol in candidates:
        verdict = agent.run(symbol, entry_mode="breakout")
        print(verdict)