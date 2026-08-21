"""Daily incremental update steps, run each market day after close.

``pipeline.main`` owns the step order and per-step failure handling; this
module only provides the individual update functions.

Most steps resume from a stored ``lastupdated`` watermark. Insider filings,
events, and 13F holdings use a fixed lookback window instead, because those
records can appear long after the date they describe.
"""

import time

import pandas as pd
from pipeline.load_data import START_DATE, load_sharadar_table
from data.sharadar_data import SharadarData
from data.technical_features import compute_technical_features

import database.source.daily_repo as daily_repo
import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo
from pipeline import report

TODAY = pd.Timestamp.today().strftime("%Y-%m-%d")


def _lookback(days: int) -> str:
    """Return the date ``days`` calendar days before today, as a string."""
    return (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _fetch(sh_fn, repo_insert, **filters) -> report.StepResult:
    """Fetch one vendor endpoint, upsert what it returns, and report the outcome.

    Fetch and insert are timed separately because a slow step is usually one or
    the other, and the difference decides whether to look at the vendor or the
    database.
    """
    scope = ", ".join(f"{key}={value}" for key, value in filters.items())
    started = time.perf_counter()
    frame = sh_fn(**filters)
    fetched = time.perf_counter() - started

    if frame.empty:
        return report.StepResult(rows=0, note=f"({scope})", detail=f"{fetched:.1f}s")

    started = time.perf_counter()
    repo_insert(frame)
    inserted = time.perf_counter() - started
    return report.StepResult(
        rows=len(frame),
        note=f"({scope})",
        detail=f"fetch {fetched:.1f}s · insert {inserted:.1f}s",
    )


def update_equity_prices(sh: SharadarData) -> report.StepResult:
    """Fetch equity bars changed since the stored watermark."""
    return _fetch(
        sh.equity_prices,
        equity_repo.insert,
        lastupdated_since=equity_repo.get_sync_cursor() or START_DATE,
    )


def update_fund_prices(sh: SharadarData) -> report.StepResult:
    """Fetch fund bars changed since the stored watermark."""
    return _fetch(
        sh.fund_prices,
        fund_repo.insert,
        lastupdated_since=fund_repo.get_sync_cursor() or START_DATE,
    )


def update_daily_valuation(sh: SharadarData) -> report.StepResult:
    """Fetch DAILY valuation rows changed since the stored watermark.

    An empty table is refused rather than backfilled: a decade of daily rows
    through the JSON API is the wrong tool, and the bulk export path exists for
    exactly that.
    """
    cursor = daily_repo.get_sync_cursor()
    if cursor is None:
        raise RuntimeError(
            "empty — bulk load it first: uv run python -m pipeline.main load daily"
        )
    return _fetch(sh.daily_valuation, daily_repo.insert, lastupdated_since=cursor)


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


def update_technical_features(batch_size: int = 200) -> report.StepResult:
    """Rebuild stale feature histories, then fill in missing dates.

    Stale tickers are rebuilt in full first and then excluded from the gap fill, so
    no ticker is computed twice. Each gap batch reads back far enough before its
    earliest missing date to warm the longest rolling window.
    """
    if technical_features_repo.is_empty():
        raise RuntimeError("no base data — load equity prices first")

    rebuilt = 0
    stale = technical_features_repo.get_stale_feature_tickers()
    if stale:
        rebuilt = _recompute_history(stale, batch_size)
        print(f"  rebuilt {rebuilt:,} rows for {len(stale):,} re-adjusted tickers")

    missing = technical_features_repo.get_missing_feature_dates()
    if stale:
        missing = missing[~missing["ticker"].isin(stale)].copy()
    if missing.empty:
        return report.StepResult(rows=rebuilt, note="(rebuilt only)" if rebuilt else "")
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
        print(f"  batch {i // batch_size + 1}/{n_batches}  (+{total:,} rows)")
    return report.StepResult(rows=total + rebuilt, note=f"({len(symbols):,} tickers)")


def update_fundamentals(sh: SharadarData) -> report.StepResult:
    """Fetch fundamentals changed since the stored watermark.

    Falls back to a 90-day window when nothing is stored yet, which is wide enough
    to catch restatements of recently closed periods.
    """
    return _fetch(
        sh.fundamentals,
        fundamentals_repo.insert,
        lastupdated_since=fundamentals_repo.get_sync_cursor() or _lookback(90),
    )


def update_insider(sh: SharadarData) -> report.StepResult:
    """Fetch insider filings disclosed in the last two weeks.

    Windowed by filing date rather than a watermark, because a filing can appear
    long after the trade it reports.
    """
    return _fetch(
        sh.insider_transactions,
        insider_repo.insert,
        start_date=_lookback(14),
        end_date=TODAY,
    )


def _reexport_quarters(code: str, repo) -> report.StepResult:
    """Re-export one quarterly table from its newest stored quarter onward.

    The 13F step skips the JSON datatable, so its rows arrive already rescaled by
    the bulk loader. Restarted at the newest stored quarter rather than after it,
    because filings arrive for weeks and the largest holders are missing from a
    quarter until they do.
    """
    since = repo.get_sync_cursor() or START_DATE
    rows = load_sharadar_table(code, start_date=since, upsert=True)
    return report.StepResult(rows=rows, note=f"(quarters from {since})")


def update_institutional() -> report.StepResult:
    """Re-export recent quarters of by-ticker 13F ownership."""
    return _reexport_quarters("SF3A", institutional_repo)


def update_events(sh: SharadarData) -> report.StepResult:
    """Fetch corporate events from the last week."""
    return _fetch(
        sh.events,
        event_repo.insert,
        start_date=_lookback(7),
        end_date=TODAY,
    )


def update_tickers(sh: SharadarData) -> report.StepResult:
    """Fetch equity and fund descriptors changed since the watermark."""
    since = tickers_repo.get_sync_cursor()
    equities = sh.tickers(table="SEP", lastupdated_since=since)
    funds = sh.tickers(table="SFP", lastupdated_since=since)
    frame = pd.concat([equities, funds], ignore_index=True)
    if frame.empty:
        return report.StepResult(rows=0)
    tickers_repo.insert(frame)
    return report.StepResult(rows=len(frame))
