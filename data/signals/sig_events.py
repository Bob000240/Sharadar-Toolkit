import pandas as pd
from dataclasses import dataclass

import database.market.event_repo as event_repo


def _has_code(series: pd.Series, code: str) -> pd.Series:
    return series.apply(
        lambda x: code in [c.strip() for c in str(x).split("|")]
        if pd.notna(x)
        else False
    )

# Sharadar EVENTS table — 8-K item codes (separated by | in eventcodes column)
_EARNINGS_CODE = "22"  # Results of Operations and Financial Condition
_ACTIVIST_CODE = "35"  # Schedule 13D (activist investor ≥5%)
_INSTIT_CODE = "34"  # Schedule 13G (institutional passive ≥5%)
_MA_CODE = "21"  # Completion of Acquisition or Disposition of Assets
_TENDER_CODE = "37"  # Tender Offer Statement
_CONTROL_CODE = "51"  # Changes in Control of Registrant
_DELISTING_CODE = "31"  # Notice of Delisting or Failure to Satisfy Listing Rule
_RESTATE_CODE = "42"  # Non-Reliance on Previously Issued Financial Statements
_BANKRUPT_CODE = "13"  # Bankruptcy or Receivership
_LATE_FILE_CODE = "36"  # Inability to Timely File 10-K or 10-Q
_IMPAIRMENT_CODE = "26"  # Material Impairments


@dataclass
class EventsSnapshot:
    ticker: str
    signal_day: pd.Timestamp

    days_since_last_earnings: int | None

    recent_event_codes: list[str]

    def risk_flags(self) -> dict[str, bool]:
        ds = self.days_since_last_earnings
        all_codes = set(self.recent_event_codes)
        return {
            "just_reported": ds is not None and ds <= 3,
            "post_earnings": ds is not None and ds <= 7,
            "delisting_risk": _DELISTING_CODE in all_codes,
            "restatement": _RESTATE_CODE in all_codes,
            "bankruptcy": _BANKRUPT_CODE in all_codes,
            "late_filing": _LATE_FILE_CODE in all_codes,
            "material_impairment": _IMPAIRMENT_CODE in all_codes,
        }

    def catalyst_flags(self) -> dict[str, bool]:
        all_codes = set(self.recent_event_codes)
        return {
            "activist_filing": _ACTIVIST_CODE in all_codes,
            "institutional_filing": _INSTIT_CODE in all_codes,
            "ma_event": _MA_CODE in all_codes,
            "tender_offer": _TENDER_CODE in all_codes,
            "change_of_control": _CONTROL_CODE in all_codes,
            "recent_events": len(self.recent_event_codes) > 0,
        }


class EventsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
        lookback_days: int = 20,
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.lookback_days = lookback_days
        self.data: dict[str, pd.DataFrame] = {}
        self.load_data()

    def load_data(self) -> None:
        start = self.signal_day - pd.Timedelta(days=self.lookback_days)
        df = event_repo.get(
            tickers=self.tickers,
            start_date=str(start.date()),
            end_date=str(self.signal_day.date()),
        )
        df["date"] = pd.to_datetime(df["date"])
        for tkr, grp in df.groupby("ticker"):
            self.data[tkr] = grp.reset_index(drop=True)

    def _days_since_last_earnings(self, tkr: str) -> int | None:
        grp = self.data.get(tkr)
        if grp is None:
            return None
        past = grp[
            (grp["date"] <= self.signal_day) &
            _has_code(grp["eventcodes"], _EARNINGS_CODE)
        ]
        if past.empty:
            return None
        return int((self.signal_day - past["date"].max()).days)

    def _event_codes_in_window(
        self, tkr: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[str]:
        grp = self.data.get(tkr)
        if grp is None:
            return []
        window = grp[(grp["date"] >= start) & (grp["date"] <= end)]
        codes = set()
        for raw in window["eventcodes"].dropna():
            for code in str(raw).split("|"):
                codes.add(code.strip())
        return sorted(codes)

    def build_snapshot(self, ticker: str) -> EventsSnapshot:
        recent_start = self.signal_day - pd.Timedelta(days=self.lookback_days)
        return EventsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            days_since_last_earnings=self._days_since_last_earnings(ticker),
            recent_event_codes=self._event_codes_in_window(
                ticker, recent_start, self.signal_day
            ),
        )


def print_snapshot_report(snap: EventsSnapshot) -> None:
    ds = (
        f"{snap.days_since_last_earnings}d"
        if snap.days_since_last_earnings is not None
        else "none"
    )
    print(f"\n=== {snap.ticker} | {snap.signal_day.date()} ===")
    print(f"  Last earnings: {ds} ago")
    print(f"  Recent codes:   {snap.recent_event_codes}")
    print(f"  Risk Flags:     {snap.risk_flags()}")
    print(f"  Catalyst Flags: {snap.catalyst_flags()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2026-06-23")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = EventsModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
