from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from agents.llm_client import ANALYSIS_MODEL


@dataclass
class AgentVerdict:
    symbol: str
    signal_type: str
    direction: Literal["bullish", "neutral", "bearish"]
    confidence: float  # 0.0 – 1.0
    reasoning: str
    sector: str = "Unknown"
    stop_price: float = 0.0
    stop_pct: float = 0.0
    target_price: float = 0.0
    target_pct: float = 0.0
    atr: float = 0.0
    max_hold_days: int = 20

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
    def __init__(self, model: str = ANALYSIS_MODEL):
        self.model = model

    @property
    @abstractmethod
    def signal_type(self) -> str: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def prefilter(self, **kwargs) -> list[str]: ...

    @abstractmethod
    def run(self, symbol: str) -> AgentVerdict: ...
