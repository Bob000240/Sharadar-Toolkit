import pandas as pd
from dataclasses import dataclass

import database.market.event_repo as event_repo

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

    days_to_next_earnings: int | None
    days_since_last_earnings: int | None

    upcoming_event_codes: list[str]
    recent_event_codes: list[str]

    def risk_flags(self) -> dict[str, bool]:
        dn = self.days_to_next_earnings
        ds = self.days_since_last_earnings
        all_codes = set(self.upcoming_event_codes + self.recent_event_codes)
        return {
            "earnings_imminent": dn is not None and dn <= 5,
            "earnings_this_week": dn is not None and dn <= 7,
            "earnings_soon": dn is not None and dn <= 14,
            "just_reported": ds is not None and ds <= 3,
            "post_earnings": ds is not None and ds <= 7,
            "delisting_risk": _DELISTING_CODE in all_codes,
            "restatement": _RESTATE_CODE in all_codes,
            "bankruptcy": _BANKRUPT_CODE in all_codes,
            "late_filing": _LATE_FILE_CODE in all_codes,
            "material_impairment": _IMPAIRMENT_CODE in all_codes,
        }

    def catalyst_flags(self) -> dict[str, bool]:
        all_codes = set(self.upcoming_event_codes + self.recent_event_codes)
        upcoming = set(self.upcoming_event_codes)
        return {
            "activist_filing": _ACTIVIST_CODE in all_codes,
            "institutional_filing": _INSTIT_CODE in all_codes,
            "ma_event": _MA_CODE in all_codes,
            "tender_offer": _TENDER_CODE in upcoming,
            "change_of_control": _CONTROL_CODE in all_codes,
            "upcoming_events": len(self.upcoming_event_codes) > 0,
            "recent_events": len(self.recent_event_codes) > 0,
        }


class EventsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
        lookback_days: int = 14,
        lookahead_days: int = 30,
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.lookback_days = lookback_days
        self.lookahead_days = lookahead_days
        self.data: dict[str, pd.DataFrame] = {}
        self._load_data()

    def _load_data(self) -> None:
        start = self.signal_day - pd.Timedelta(days=self.lookback_days)
        end = self.signal_day + pd.Timedelta(days=self.lookahead_days)
        df = event_repo.get(
            tickers=self.tickers,
            start_date=str(start.date()),
            end_date=str(end.date()),
        )
        df["date"] = pd.to_datetime(df["date"])
        for tkr, grp in df.groupby("ticker"):
            self.data[tkr] = grp.reset_index(drop=True)

    def _days_to_next_earnings(self, tkr: str) -> int | None:
        grp = self.data.get(tkr)
        if grp is None:
            return None
        future = grp[
            (grp["date"] > self.signal_day)
            & (
                grp["eventcodes"].str.contains(
                    rf"(^|\|){_EARNINGS_CODE}(\||$)", na=False, regex=True
                )
            )
        ]
        if future.empty:
            return None
        return int((future["date"].min() - self.signal_day).days)

    def _days_since_last_earnings(self, tkr: str) -> int | None:
        grp = self.data.get(tkr)
        if grp is None:
            return None
        past = grp[
            (grp["date"] <= self.signal_day)
            & (
                grp["eventcodes"].str.contains(
                    rf"(^|\|){_EARNINGS_CODE}(\||$)", na=False, regex=True
                )
            )
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
        upcoming_end = self.signal_day + pd.Timedelta(days=self.lookahead_days)
        return EventsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            days_to_next_earnings=self._days_to_next_earnings(ticker),
            days_since_last_earnings=self._days_since_last_earnings(ticker),
            upcoming_event_codes=self._event_codes_in_window(
                ticker, self.signal_day + pd.Timedelta(days=1), upcoming_end
            ),
            recent_event_codes=self._event_codes_in_window(
                ticker, recent_start, self.signal_day
            ),
        )


def print_snapshot_report(snap: EventsSnapshot) -> None:
    dn = (
        f"{snap.days_to_next_earnings}d"
        if snap.days_to_next_earnings is not None
        else "none"
    )
    ds = (
        f"{snap.days_since_last_earnings}d"
        if snap.days_since_last_earnings is not None
        else "none"
    )
    print(f"\n=== {snap.ticker} | {snap.signal_day.date()} ===")
    print(f"  Next earnings: {dn}  |  Last earnings: {ds} ago")
    print(f"  Upcoming codes: {snap.upcoming_event_codes}")
    print(f"  Recent codes:   {snap.recent_event_codes}")
    print(f"  Risk Flags:     {snap.risk_flags()}")
    print(f"  Catalyst Flags: {snap.catalyst_flags()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2025-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = EventsModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
