from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
import pandas as pd
from agents.llm_client import call_llm_analyze, call_llm_verdict, ANALYSIS_MODEL, VERDICT_MODEL


@dataclass
class AgentVerdict:
    symbol: str
    signal_type: str
    direction: Literal["bullish", "neutral", "bearish"]
    confidence: float  # 0.0 – 1.0
    reasoning: str

    def __str__(self) -> str:
        return (
            f"AgentVerdict(\n"
            f"  symbol={self.symbol!r},\n"
            f"  signal_type={self.signal_type!r},\n"
            f"  direction={self.direction!r},\n"
            f"  confidence={self.confidence:.2f} ({self.confidence:.0%}),\n"
            f"  reasoning={self.reasoning!r},\n"
            f")"
        )


class SignalAgent(ABC):
    def __init__(self, model: str = ANALYSIS_MODEL, verdict_model: str = VERDICT_MODEL):
        self.model = model
        self.verdict_model = verdict_model

    @property
    @abstractmethod
    def signal_type(self) -> str: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    def _parse_verdict(self, raw: dict) -> tuple[str, float]:
        direction = str(raw.get("direction", "neutral")).lower()
        if direction not in ("bullish", "neutral", "bearish"):
            direction = "neutral"
        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5
        return direction, confidence

    def prefilter(self, symbols: list[str], as_of: pd.Timestamp) -> list[str]:
        return symbols

    def analyze(self, snapshot) -> str:
        return call_llm_analyze(self.system_prompt, snapshot.to_agent_prompt(), self.model)

    def verdict(self, thesis: str) -> dict:
        return call_llm_verdict(thesis, self.verdict_model)

    def run(self, snapshot) -> AgentVerdict:
        thesis = self.analyze(snapshot)
        direction, confidence = self._parse_verdict(self.verdict(thesis))
        return AgentVerdict(
            symbol=snapshot.symbol,
            signal_type=self.signal_type,
            direction=direction,
            confidence=confidence,
            reasoning=thesis,
        )
