from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

@dataclass
class AgentVerdict:
    symbol: str
    strategy: str
    direction: Literal["bullish", "neutral", "bearish"]
    confidence: float
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
            f"  strategy={self.strategy!r},\n"
            f"  direction={self.direction!r},\n"
            f"  confidence={self.confidence:.2f} ({self.confidence:.0%}),\n"
            f"  reasoning={self.reasoning!r},\n"
            f")"
        )


class SignalAgent(ABC):
    def __init__(self, model: str = None):
        self.model = model

    @abstractmethod
    def pre_filter(self, **kwargs) -> list[str]: ...

    @abstractmethod
    def run(self, symbol: str) -> AgentVerdict: ...