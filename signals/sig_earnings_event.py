import database.earnings_repository as earnings_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class EarningsEventSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp

    # Timing
    next_earnings_date: pd.Timestamp
    days_to_earnings:   int

    # Event setup
    implied_move_pct:    float      # options-implied expected move on earnings day
    estimate_dispersion: float      # std dev of analyst EPS estimates; lower = more consensus

    # Surprise history (last 4 quarters; positive = beat, negative = miss)
    eps_surprise_1q: float          # most recent quarter
    eps_surprise_2q: float
    eps_surprise_3q: float
    eps_surprise_4q: float          # oldest of the 4
    mean_eps_surprise: float        # average of above 4

    # Forward-looking signals
    pead_signal:                str     # "positive", "negative", "neutral"
    estimate_revision_direction: str    # "up", "down", "flat"

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    def _fmt_header(self) -> str:
        urgency = (
            "IMMINENT (< 7 days)"  if self.days_to_earnings <= 7  else
            "NEAR-TERM (< 30 days)" if self.days_to_earnings <= 30 else
            "upcoming"
        )
        return "\n".join([
            f"EARNINGS EVENT ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Next earnings: {self.next_earnings_date.date()}  ({self.days_to_earnings} days away — {urgency})",
        ])

    def _fmt_event_setup(self) -> str:
        dispersion_note = (
            "low — strong analyst consensus"
            if self.estimate_dispersion < 0.05
            else ("moderate" if self.estimate_dispersion < 0.15 else "high — wide estimate spread, outcome uncertain")
        )
        return "\n".join([
            "--- EVENT SETUP ---",
            f"  Implied options move (±):  {abs(self.implied_move_pct):.1%}  (market pricing in this reaction at earnings)",
            f"  Estimate dispersion (std): {self.estimate_dispersion:.2f}  ({dispersion_note})",
        ])

    def _fmt_surprise_history(self) -> str:
        consistent_beat = all(
            v > 0 for v in [self.eps_surprise_1q, self.eps_surprise_2q,
                            self.eps_surprise_3q, self.eps_surprise_4q]
        )
        summary_note = "consistent beater (all 4 quarters positive)" if consistent_beat else ""
        lines = [
            "--- EPS SURPRISE HISTORY (last 4 quarters) ---",
            f"  Q-1 (most recent):  {self._pct(self.eps_surprise_1q)}",
            f"  Q-2:                {self._pct(self.eps_surprise_2q)}",
            f"  Q-3:                {self._pct(self.eps_surprise_3q)}",
            f"  Q-4:                {self._pct(self.eps_surprise_4q)}",
            f"  Mean surprise:      {self._pct(self.mean_eps_surprise)}",
        ]
        if summary_note:
            lines.append(f"  Note: {summary_note}")
        return "\n".join(lines)

    def _fmt_forward_signals(self) -> str:
        pead_note = {
            "positive": "stock historically drifts UP after beats — PEAD tailwind",
            "negative": "stock historically drifts DOWN after misses — PEAD headwind",
            "neutral":  "no clear post-earnings drift pattern",
        }.get(self.pead_signal, self.pead_signal)

        revision_note = {
            "up":   "analysts RAISING estimates — positive pre-earnings momentum",
            "down": "analysts CUTTING estimates — negative pre-earnings momentum",
            "flat": "estimates stable",
        }.get(self.estimate_revision_direction, self.estimate_revision_direction)

        return "\n".join([
            "--- POST-EARNINGS DRIFT & REVISIONS ---",
            f"  PEAD signal:               {self.pead_signal}  ({pead_note})",
            f"  Estimate revision trend:   {self.estimate_revision_direction}  ({revision_note})",
        ])

    def to_agent_prompt(self) -> str:
        return "\n\n".join([
            self._fmt_header(),
            self._fmt_event_setup(),
            self._fmt_surprise_history(),
            self._fmt_forward_signals(),
        ])


class EarningsEventFactorsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str] | str,
    ):
        self.signal_day = signal_day
        self.stock_symbols = [stock_symbols] if isinstance(stock_symbols, str) else stock_symbols
        self.stock_data = None
        self._load_data()

    def _load_data(self):
        earnings = earnings_repo.get_latest_earnings(self.stock_symbols, self.signal_day)
        earnings = earnings.set_index("symbol")

        # Recompute days_to_earnings from stored next_earnings_date to keep it current
        earnings["next_earnings_date"] = pd.to_datetime(earnings["next_earnings_date"])
        earnings["days_to_earnings"] = (
            earnings["next_earnings_date"] - self.signal_day
        ).dt.days

        self.stock_data = earnings

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> EarningsEventSnapshot:
        return EarningsEventSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            next_earnings_date=self.get(symbol, "next_earnings_date"),
            days_to_earnings=int(self.get(symbol, "days_to_earnings")),
            implied_move_pct=self.get(symbol, "implied_move_pct"),
            estimate_dispersion=self.get(symbol, "estimate_dispersion"),
            eps_surprise_1q=self.get(symbol, "eps_surprise_1q"),
            eps_surprise_2q=self.get(symbol, "eps_surprise_2q"),
            eps_surprise_3q=self.get(symbol, "eps_surprise_3q"),
            eps_surprise_4q=self.get(symbol, "eps_surprise_4q"),
            mean_eps_surprise=self.get(symbol, "mean_eps_surprise"),
            pead_signal=self.get(symbol, "pead_signal"),
            estimate_revision_direction=self.get(symbol, "estimate_revision_direction"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = EarningsEventFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
