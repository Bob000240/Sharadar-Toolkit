from dataclasses import dataclass, field
from typing import Literal
from agents.sa_agents.sa import AgentVerdict, SignalAgent


_DIR_SCORE = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


@dataclass
class ReconcilerResult:
    symbol: str
    composite_score: float      # confidence-weighted direction: -1.0 to +1.0
    direction: Literal["bullish", "neutral", "bearish"]
    avg_confidence: float       # mean confidence across contributing agents
    agent_count: int
    verdicts: list[AgentVerdict] = field(default_factory=list)

    def __str__(self) -> str:
        verdict_lines = "\n".join(
            f"    [{v.signal_type}] {v.direction} ({v.confidence:.0%})"
            for v in self.verdicts
        )
        return (
            f"ReconcilerResult(\n"
            f"  symbol={self.symbol!r},\n"
            f"  direction={self.direction!r},\n"
            f"  composite_score={self.composite_score:+.3f},\n"
            f"  avg_confidence={self.avg_confidence:.0%},\n"
            f"  agents={self.agent_count},\n"
            f"  verdicts=[\n{verdict_lines}\n"
            f"  ],\n"
            f")"
        )


class ReconcilerAgent:
    """
    Orchestrates one or more SignalAgents, aggregates their verdicts per symbol,
    and returns a ranked list of ReconcilerResults.

    agent_configs: per-signal-type kwargs forwarded to prefilter() and run().
    Example:
        {
            "quality_momentum": {
                "prefilter": {"entry_mode": "breakout"},
                "run":       {"entry_mode": "breakout"},
            }
        }
    """

    def __init__(self, agents: list[SignalAgent]):
        self.agents = agents

    def _aggregate(self, symbol: str, verdicts: list[AgentVerdict]) -> ReconcilerResult:
        total_weight = sum(v.confidence for v in verdicts) or 1e-9
        composite = sum(_DIR_SCORE[v.direction] * v.confidence for v in verdicts) / total_weight
        avg_conf = total_weight / len(verdicts)

        if composite > 0.2:
            direction = "bullish"
        elif composite < -0.2:
            direction = "bearish"
        else:
            direction = "neutral"

        return ReconcilerResult(
            symbol=symbol,
            composite_score=round(composite, 4),
            direction=direction,
            avg_confidence=round(avg_conf, 4),
            agent_count=len(verdicts),
            verdicts=verdicts,
        )

    def run(
        self,
        agent_configs: dict[str, dict] | None = None,
        min_composite: float = 0.2,
    ) -> list[ReconcilerResult]:
        """
        Run all registered agents and return bullish candidates ranked by composite_score.
        Only symbols with composite_score >= min_composite are returned.
        """
        agent_configs = agent_configs or {}
        symbol_verdicts: dict[str, list[AgentVerdict]] = {}

        for agent in self.agents:
            cfg = agent_configs.get(agent.signal_type, {})
            prefilter_cfg = cfg.get("prefilter", {})
            run_cfg = cfg.get("run", {})

            try:
                candidates = agent.prefilter(**prefilter_cfg)
            except Exception as e:
                print(f"[{agent.signal_type}] prefilter error: {e}")
                continue

            print(f"[{agent.signal_type}] {len(candidates)} candidates after prefilter")

            for symbol in candidates:
                try:
                    verdict = agent.run(symbol, **run_cfg)
                    symbol_verdicts.setdefault(symbol, []).append(verdict)
                except Exception as e:
                    print(f"[{agent.signal_type}] run error for {symbol}: {e}")

        results = [
            self._aggregate(sym, verdicts)
            for sym, verdicts in symbol_verdicts.items()
        ]
        bullish = [r for r in results if r.composite_score >= min_composite]
        bullish.sort(key=lambda r: r.composite_score, reverse=True)
        return bullish


if __name__ == "__main__":
    from agents.sa_agents.sa_RS import QualityMomentumAgent

    agent = QualityMomentumAgent()
    reconciler = ReconcilerAgent([agent])

    results = reconciler.run(
        agent_configs={
            "quality_momentum": {
                "prefilter": {"entry_mode": "breakout"},
                "run":       {"entry_mode": "breakout"},
            }
        }
    )

    print(f"\n=== Top Picks ({len(results)} bullish) ===")
    for r in results[:10]:
        print(r)
        print()
