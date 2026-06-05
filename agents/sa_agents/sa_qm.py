from agents.sa_agents.sa import SignalAgent, AgentVerdict
from agents.llm_client import call_llm_analyze, ANALYSIS_MODEL, VERDICT_MODEL

QUALITY_SECTIONS  = ["profitability", "cash_quality"]
MOMENTUM_SECTIONS = ["absolute_momentum", "benchmark_relative", "trend_structure"]
GROWTH_SECTIONS   = ["eps_growth", "estimate_revisions"]
VALUE_SECTIONS    = ["earnings_valuation"]

_SYSTEM_PROMPT = """You are a quantitative equity analyst specialising in Quality-Momentum investing.

Your job: read a stock's quality, momentum, growth, and valuation data, then write a clear investment thesis.

=== FRAMEWORK ===

QUALITY (non-negotiable filter)
- Want: ROIC > 15%, FCF margin positive, cash conversion > 1.0 (earnings backed by real cash)
- Reject: negative FCF margin or accruals ratio > 0.1, regardless of other signals
- A great business in a downtrend still beats a junk stock in an uptrend

MOMENTUM (primary timing signal)
- Want: price above SMA 200, outperforming the S&P 500 and sector peers, trend R² > 0.6
- Bearish flag: underperforming market on both 5d and 20d windows, or below SMA 200
- Trend structure matters more than raw return: a smooth uptrend beats a volatile spike

GROWTH (leading signal)
- Analyst EPS revisions are the most forward-looking input — act on upgrades before price moves
- Want: EPS growth YoY positive and accelerating, revisions trending upward
- Revision direction > revision magnitude

VALUATION (guardrail only — you are not a value investor)
- Use earnings yield to avoid paying an egregious premium
- Do not penalise a quality compounder for a reasonable P/E premium
- Reject only if the stock is priced for perfection with no margin for error

=== SCORING LOGIC ===
BULLISH:  quality top-quartile + price uptrend above SPY + EPS revisions positive + valuation not extreme
NEUTRAL:  one signal clearly broken, or mixed quality/momentum signals
BEARISH:  quality deteriorating OR momentum broken vs. market OR EPS revisions turning negative

=== OUTPUT FORMAT ===
Write a concise investment thesis (3-5 paragraphs). Structure:
1. Quality assessment — is this a fundamentally sound business?
2. Momentum read — what is the market saying about the stock right now?
3. Growth/revision signal — are fundamentals improving or deteriorating?
4. Valuation check — is the price reasonable given the above?
5. Final verdict — bullish / neutral / bearish, conviction level (0-1), and the single biggest risk.

Be specific. Cite actual numbers from the data. Do not hedge every sentence."""


class QualityMomentumAgent(SignalAgent):
    def __init__(
        self,
        analysis_model: str = ANALYSIS_MODEL,
        verdict_model: str = VERDICT_MODEL,
    ):
        super().__init__(model=analysis_model, verdict_model=verdict_model)

    @property
    def signal_type(self) -> str:
        return "quality_momentum"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def analyze(self, quality_snap, momentum_snap, growth_snap, value_snap) -> str:
        combined = "\n\n".join([
            quality_snap.to_agent_prompt(),
            momentum_snap.to_agent_prompt(),
            growth_snap.to_agent_prompt(),
            value_snap.to_agent_prompt(),
        ])
        return call_llm_analyze(self.system_prompt, combined, self.model)

    def run(self, quality_snap, momentum_snap, growth_snap, value_snap) -> AgentVerdict:
        thesis = self.analyze(quality_snap, momentum_snap, growth_snap, value_snap)
        direction, confidence = self._parse_verdict(self.verdict(thesis))
        return AgentVerdict(
            symbol=quality_snap.symbol,
            signal_type=self.signal_type,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
        )


if __name__ == "__main__":
    import pandas as pd
    from signals.sig_quality  import QualityFactorsModel
    from signals.sig_momentum import MomentumFactorsModel
    from signals.sig_growth   import GrowthFactorsModel
    from signals.sig_value    import ValueFactorsModel

    symbols     = ["GOOGL"]
    etf_symbols = ["XLK", "XLY", "XLC", "XLF", "XLV", "XLI", "XLE", "XLB", "XLRE", "XLU", "XLP"]
    benchmark   = "SPY"
    signal_day  = pd.Timestamp.today()

    quality_model  = QualityFactorsModel(signal_day, symbols)
    momentum_model = MomentumFactorsModel(signal_day, symbols, benchmark, etf_symbols)
    growth_model   = GrowthFactorsModel(signal_day, symbols)
    value_model    = ValueFactorsModel(signal_day, symbols)

    agent = QualityMomentumAgent()

    for sym in symbols:
        result = agent.run(
            quality_model.build_snapshot(sym, QUALITY_SECTIONS),
            momentum_model.build_snapshot(sym, MOMENTUM_SECTIONS),
            growth_model.build_snapshot(sym, GROWTH_SECTIONS),
            value_model.build_snapshot(sym, VALUE_SECTIONS),
        )
        print(result)
        print()
