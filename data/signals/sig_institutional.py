import pandas as pd
from dataclasses import dataclass

import database.market.institutional_repo as institutional_repo

# 13F filings are due 45 days after quarter end — use this offset for point-in-time safety.
_FILING_DELAY_DAYS = 45
_SHARE_TYPE = "SHR"


@dataclass
class InstitutionalSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    quarter_end: pd.Timestamp | None
    assumed_available_from: pd.Timestamp | None
    stale_days: int | None
    availability_is_estimated: bool

    # Most recent conservatively available reported quarter
    total_holders: int
    total_value_b: float  # USD billions
    total_units: float  # shares held

    # Quarter-over-quarter changes
    holders_change: int
    value_change_pct: float  # NaN if no prior quarter
    units_change_pct: float  # NaN if no prior quarter
    new_holders: int  # institutions that opened new positions
    closed_positions: int  # institutions that fully exited


class InstitutionalModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        tickers: list[str],
    ):
        self.signal_day = signal_day
        self.tickers = tickers
        self.data: dict[str, pd.DataFrame] = {}
        self.load_data()

    def load_data(self) -> None:
        # 45-day filing delay: latest visible quarter end is signal_day - 45d
        cutoff = self.signal_day - pd.Timedelta(days=_FILING_DELAY_DAYS)
        # Fetch ~2 quarters of history to compute QoQ changes
        start = cutoff - pd.Timedelta(days=200)
        df = institutional_repo.get(
            tickers=self.tickers,
            start_date=str(start.date()),
            end_date=str(cutoff.date()),
        )
        if df.empty:
            return
        df["calendardate"] = pd.to_datetime(df["calendardate"])
        df = df[df["securitytype"] == _SHARE_TYPE]
        for tkr, grp in df.groupby("ticker"):
            self.data[tkr] = grp.reset_index(drop=True)

    def _agg(self, tkr: str) -> dict:
        _empty = dict(
            quarter_end=None,
            assumed_available_from=None,
            stale_days=None,
            availability_is_estimated=True,
            total_holders=0,
            total_value_b=0.0,
            total_units=0.0,
            holders_change=0,
            value_change_pct=float("nan"),
            units_change_pct=float("nan"),
            new_holders=0,
            closed_positions=0,
        )
        grp = self.data.get(tkr)
        if grp is None or grp.empty:
            return _empty

        quarters = sorted(grp["calendardate"].unique())
        if len(quarters) == 0:
            return _empty

        latest_q = pd.Timestamp(quarters[-1])
        available_from = latest_q + pd.Timedelta(days=_FILING_DELAY_DAYS)
        stale_days = int((self.signal_day.normalize() - latest_q).days)
        curr = grp[grp["calendardate"] == latest_q]

        curr_holders = curr["investorname"].nunique()
        curr_value = float(curr["value"].fillna(0).sum())
        curr_units = float(curr["units"].fillna(0).sum())

        if len(quarters) >= 2:
            prior_q = quarters[-2]
            prev = grp[grp["calendardate"] == prior_q]

            prev_holders = prev["investorname"].nunique()
            prev_value = float(prev["value"].fillna(0).sum())
            prev_units = float(prev["units"].fillna(0).sum())

            curr_names = set(curr["investorname"])
            prev_names = set(prev["investorname"])

            return dict(
                quarter_end=latest_q,
                assumed_available_from=available_from,
                stale_days=stale_days,
                availability_is_estimated=True,
                total_holders=curr_holders,
                total_value_b=curr_value / 1e9,
                total_units=curr_units,
                holders_change=curr_holders - prev_holders,
                value_change_pct=(curr_value - prev_value) / prev_value
                if prev_value != 0
                else float("nan"),
                units_change_pct=(curr_units - prev_units) / prev_units
                if prev_units != 0
                else float("nan"),
                new_holders=len(curr_names - prev_names),
                closed_positions=len(prev_names - curr_names),
            )

        return dict(
            quarter_end=latest_q,
            assumed_available_from=available_from,
            stale_days=stale_days,
            availability_is_estimated=True,
            total_holders=curr_holders,
            total_value_b=curr_value / 1e9,
            total_units=curr_units,
            holders_change=0,
            value_change_pct=float("nan"),
            units_change_pct=float("nan"),
            new_holders=0,
            closed_positions=0,
        )

    def build_snapshot(self, ticker: str) -> InstitutionalSnapshot:
        m = self._agg(ticker)
        return InstitutionalSnapshot(ticker=ticker, signal_day=self.signal_day, **m)


def print_snapshot_report(snap: InstitutionalSnapshot) -> None:
    quarter_end = str(snap.quarter_end.date()) if snap.quarter_end is not None else "n/a"
    available_from = (
        str(snap.assumed_available_from.date())
        if snap.assumed_available_from is not None
        else "n/a"
    )
    vpc = (
        f"{snap.value_change_pct:+.1%}" if not pd.isna(snap.value_change_pct) else "n/a"
    )
    upc = (
        f"{snap.units_change_pct:+.1%}" if not pd.isna(snap.units_change_pct) else "n/a"
    )
    print(f"\n=== {snap.ticker} | {snap.signal_day.date()} ===")
    print(
        f"  Reported quarter: {quarter_end}  |  assumed available: {available_from}"
        f"  |  stale: {snap.stale_days if snap.stale_days is not None else 'n/a'}d"
    )
    print(f"  Holders: {snap.total_holders}  (Δ {snap.holders_change:+d})")
    print(
        f"  Value: ${snap.total_value_b:,.1f}B  (QoQ {vpc})  |  Units: {snap.total_units:,.0f}  (QoQ {upc})"
    )
    print(
        f"  New entrants: {snap.new_holders}  |  Closed positions: {snap.closed_positions}"
    )


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    tickers = ["AAPL", "MSFT", "GOOGL"]

    model = InstitutionalModel(signal_day=signal_day, tickers=tickers)
    for tkr in tickers:
        print_snapshot_report(model.build_snapshot(tkr))
