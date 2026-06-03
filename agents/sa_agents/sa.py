from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass
class AgentVerdict:
    symbol: str
    signal_type: str
    direction: Literal["bullish", "neutral", "bearish"]
    confidence: float  # 0.0 – 1.0
    reasoning: str     # full thesis from analyze()
    precentage_allocation: float

    def __str__(self) -> str:
        return (
            f"AgentVerdict(\n"
            f"  symbol={self.symbol!r},\n"
            f"  signal_type={self.signal_type!r},\n"
            f"  direction={self.direction!r},\n"
            f"  confidence={self.confidence:.2f} ({self.confidence:.0%}),\n"
            f"  reasoning={self.reasoning!r},\n"
            f"  precentage_allocation={self.precentage_allocation:.2f} "
            f"({self.precentage_allocation:.0%})\n"
            f")"
        )


class SignalAgent(ABC):
    def __init__(self, model: str):
        self.model = model

    @property
    @abstractmethod
    def signal_type(self) -> str: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    def analyze(self, snapshot) -> str:
        """gpt-4o reads snapshot data and writes a free-text investment thesis."""
        from agents.llm_client import call_llm_analyze
        return call_llm_analyze(self.system_prompt, snapshot.to_agent_prompt(), self.model)

    def verdict(self, thesis: str) -> dict:
        """gpt-4o-mini reads the thesis and returns a structured JSON verdict."""
        from agents.llm_client import call_llm_verdict
        return call_llm_verdict(thesis)

    def run(self, snapshot) -> AgentVerdict:
        """Full pipeline: analyze → verdict → AgentVerdict."""
        thesis = self.analyze(snapshot)
        raw    = self.verdict(thesis)

        direction = str(raw.get("direction", "neutral")).lower()
        if direction not in ("bullish", "neutral", "bearish"):
            direction = "neutral"

        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        allocation = confidence if direction == "bullish" else 0.0

        return AgentVerdict(
            symbol=snapshot.symbol,
            signal_type=self.signal_type,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
            precentage_allocation=allocation,
        )
