"""Daily incremental update steps, run each market day after close.

::

    uv run python -m pipeline.main update

``pipeline.main`` owns the step order and the per-step failure handling; this
module only provides the individual update functions.

Most steps resume from a stored ``lastupdated`` watermark and ask the vendor only
for rows changed since. Insider filings, events, and 13F holdings use a fixed
lookback window instead, because those records can appear long after the date
they describe.
"""

import time

import pandas as pd
from pipeline.config import BENCHMARK_SYMBOLS
from pipeline.load_data import START_DATE
from data.sharadar_data import SharadarData
from data.technical_features import compute_technical_features

import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo

TODAY = pd.Timestamp.today().strftime("%Y-%m-%d")


def _lookback(days: int) -> str:
    """Return the date ``days`` calendar days before today, as a string."""
    return (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _fetch(sh_fn, repo_insert, label: str, batch_size: int = 0, **filters) -> None:
    """Fetch one vendor endpoint and upsert what it returns.

    With ``batch_size`` set, the ticker list is split into batches and each is
    fetched and written before the next, so a large request cannot time out as one
    call. Progress and timings are printed because this runs unattended.
    """
    scope = ", ".join(f"{k}={v}" for k, v in filters.items() if k != "tickers")

    if batch_size:
        tickers = list(filters.pop("tickers"))
        n_batches = -(-len(tickers) // batch_size)
        print(
            f"{label}: fetching {len(tickers):,} tickers "
            f"in {n_batches} batches ({scope})...",
            flush=True,
        )
        started = time.perf_counter()
        total = 0
        for i in range(0, len(tickers), batch_size):
            df = sh_fn(tickers=tickers[i : i + batch_size], **filters)
            if not df.empty:
                repo_insert(df)
                total += len(df)
            print(
                f"  {label} batch {i // batch_size + 1}/{n_batches} (+{total:,} rows)",
                flush=True,
            )
        elapsed = time.perf_counter() - started
        print(f"{label}: {total:,} rows upserted ({scope}) [{elapsed:.1f}s]")
        return

    print(f"{label}: fetching ({scope})...", flush=True)
    started = time.perf_counter()
    df = sh_fn(**filters)
    fetch_elapsed = time.perf_counter() - started
    if df.empty:
        print(f"{label}: up to date [{fetch_elapsed:.1f}s]")
        return
    print(
        f"{label}: got {len(df):,} rows in {fetch_elapsed:.1f}s, upserting...",
        flush=True,
    )
    insert_started = time.perf_counter()
    repo_insert(df)
    insert_elapsed = time.perf_counter() - insert_started
    print(
        f"{label}: {len(df):,} rows upserted ({scope}) "
        f"[fetch {fetch_elapsed:.1f}s, insert {insert_elapsed:.1f}s]"
    )


def update_equity_prices(sh: SharadarData):
    """Fetch equity bars changed since the stored watermark."""
    _fetch(
        sh.equity_prices,
        equity_repo.insert,
        "Equity prices",
        lastupdated_since=equity_repo.get_sync_cursor() or START_DATE,
    )


def update_fund_prices(sh: SharadarData):
    """Fetch benchmark fund bars changed since the stored watermark."""
    _fetch(
        sh.fund_prices,
        fund_repo.insert,
        "Fund prices",
        lastupdated_since=fund_repo.get_sync_cursor() or START_DATE,
        tickers=BENCHMARK_SYMBOLS,
    )


def _recompute_history(symbols: list[str], batch_size: int) -> int:
    """Rebuild these tickers' entire feature history from their current prices.

    Every rolling window — SMA-200, the 252-day return, OBV — depends on the full
    series, so a re-adjusted price invalidates the whole history rather than just
    the recent rows. Return the number of rows written.
    """
    total = 0
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        df = equity_repo.get(tickers=batch, start_date=START_DATE)
        if df.empty:
            continue
        parts = [
            compute_technical_features(g.reset_index(drop=True))
            for _, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False)
        ]
        rows = pd.concat(parts, ignore_index=True)
        technical_features_repo.insert(rows)
        total += len(rows)
    return total


def update_technical_features(batch_size: int = 200):
    """Rebuild stale feature histories, then fill in missing dates.

    Stale tickers are rebuilt in full first and then excluded from the gap fill, so
    no ticker is computed twice. Each gap batch reads back far enough before its
    earliest missing date to warm the longest rolling window.
    """
    if technical_features_repo.is_empty():
        print("Technical features: no base data")
        return

    stale = technical_features_repo.get_stale_feature_tickers()
    if stale:
        rebuilt = _recompute_history(stale, batch_size)
        print(
            f"Technical features: rebuilt {rebuilt:,} rows for "
            f"{len(stale):,} re-adjusted tickers"
        )

    missing = technical_features_repo.get_missing_feature_dates()
    if stale:
        missing = missing[~missing["ticker"].isin(stale)].copy()
    if missing.empty:
        print("Technical features: up to date")
        return
    missing["date"] = pd.to_datetime(missing["date"])
    missing_dates = {
        ticker: set(group["date"])
        for ticker, group in missing.groupby("ticker", sort=False)
    }
    symbols = list(missing_dates)

    total = 0
    n_batches = -(-len(symbols) // batch_size)
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        earliest_gap = min(date for ticker in batch for date in missing_dates[ticker])
        lookback = (earliest_gap - pd.Timedelta(days=400)).date()
        df = equity_repo.get(tickers=batch, start_date=str(lookback))
        if df.empty:
            continue
        new_parts = []
        for tk, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False):
            features = compute_technical_features(g.reset_index(drop=True))
            features["date"] = pd.to_datetime(features["date"])
            wanted = features["date"].isin(missing_dates[tk])
            new_parts.append(features[wanted])
        new_rows = pd.concat(new_parts, ignore_index=True)
        if not new_rows.empty:
            technical_features_repo.insert(new_rows)
            total += len(new_rows)
        print(
            f"  technical features batch {i // batch_size + 1}/{n_batches}  "
            f"(+{total:,} rows)"
        )
    print(f"Technical features: {total:,} new rows ({len(symbols):,} tickers)")


def update_fundamentals(sh: SharadarData):
    """Fetch fundamentals changed since the stored watermark.

    Falls back to a 90-day window when nothing is stored yet, which is wide enough
    to catch restatements of recently closed periods.
    """
    _fetch(
        sh.fundamentals,
        fundamentals_repo.insert,
        "Fundamentals",
        lastupdated_since=fundamentals_repo.get_sync_cursor() or _lookback(90),
    )


def update_insider(sh: SharadarData):
    """Fetch insider filings disclosed in the last two weeks.

    Windowed by filing date rather than a watermark, because a filing can appear
    long after the trade it reports.
    """
    _fetch(
        sh.insider_transactions,
        insider_repo.insert,
        "Insider",
        start_date=_lookback(14),
        end_date=TODAY,
    )


def update_institutional(sh: SharadarData):
    """Fetch 13F holdings for every equity ticker, in batches.

    Batched because the ticker list is too long for one request.
    """
    _fetch(
        sh.institutional_holdings,
        institutional_repo.insert,
        "Institutional",
        batch_size=500,
        tickers=tickers_repo.get(table_code="SEP")["ticker"].tolist(),
        start_date=_lookback(60),
        end_date=TODAY,
    )


def update_events(sh: SharadarData):
    """Fetch corporate events from the last week."""
    _fetch(
        sh.events,
        event_repo.insert,
        "Events",
        start_date=_lookback(7),
        end_date=TODAY,
    )


def update_tickers(sh: SharadarData):
    """Fetch equity and benchmark descriptors changed since the watermark."""
    since = tickers_repo.get_sync_cursor()
    equities = sh.tickers(table="SEP", lastupdated_since=since)
    funds = sh.tickers(table="SFP", tickers=BENCHMARK_SYMBOLS, lastupdated_since=since)
    df = pd.concat([equities, funds], ignore_index=True)
    if df.empty:
        print("Tickers: up to date")
        return
    tickers_repo.insert(df)
    print(f"Tickers: {len(df):,} upserted")
