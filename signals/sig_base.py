from abc import ABC, abstractmethod
import pandas as pd


class SignalSnapshot(ABC):
    symbol: str
    signal_day: pd.Timestamp

    @abstractmethod
    def to_agent_prompt(self) -> str: ...


class SignalModel(ABC):
    @abstractmethod
    def build_snapshot(self, symbol: str) -> SignalSnapshot: ...
