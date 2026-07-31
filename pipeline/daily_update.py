"""
Daily incremental update. Run each market day after close.
    uv run python -m pipeline.daily_update
"""

import pandas as pd
from pipeline.config import BENCHMARK_SYMBOLS
from pipeline.load_data import START_DATE
from data.sharadar_data import SharadarData
from data.macro_data import MacroData
from data.technical_features import compute_technical_features

import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
import database.source.technical_features_repo as technical_features_repo
import database.source.tickers_repo as tickers_repo
import database.source.fundamentals_repo as fundamentals_repo
import database.source.insider_repo as insider_repo
import database.source.institutional_repo as institutional_repo
import database.source.event_repo as event_repo
import database.source.macro_repo as macro_repo

TODAY = pd.Timestamp.today().strftime("%Y-%m-%d")


def _lookback(days: int) -> str:
    return (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _fetch(sh_fn, repo_insert, label: str, **filters) -> None:
    """Fetch the whole cross-section matching `filters` and upsert it. Sharadar
    paginates it in one logical call.

    Callers pass `lastupdated_since=` where Sharadar exposes that watermark
    (SEP/SFP/SF1/TICKERS) — the only filter that surfaces revisions to rows we
    already hold. The rest can only window on the row's own date, which means
    they lose anything that falls outside the window while we weren't looking.
    """
    df = sh_fn(**filters)
    if df.empty:
        print(f"{label}: up to date")
        return
    repo_insert(df)
    scope = ", ".join(f"{k}={v}" for k, v in filters.items() if k != "tickers")
    print(f"{label}: {len(df):,} rows upserted ({scope})")


# ── prices ────────────────────────────────────────────────────────────────────


def update_equity_prices(sh: SharadarData):
    # Sync on `lastupdated`, not on `date`. A split makes Sharadar re-adjust the
    # ticker's ENTIRE price history, and those rewritten rows keep their original
    # (old) dates — a date cursor would never request them again, so the stale
    # pre-split prices would persist forever and corrupt every technical feature
    # derived from them. This also retires the old "which tickers are still
    # trading" heuristic: a delisted name simply stops being re-stamped.
    _fetch(
        sh.equity_prices,
        equity_repo.insert,
        "Equity prices",
        lastupdated_since=equity_repo.get_sync_cursor() or START_DATE,
    )


def update_fund_prices(sh: SharadarData):
    # Funds are a fixed curated set (benchmark + sector ETFs), not the equity
    # universe — fetch exactly those, incrementally.
    _fetch(
        sh.fund_prices,
        fund_repo.insert,
        "Fund prices",
        lastupdated_since=fund_repo.get_sync_cursor() or START_DATE,
        tickers=BENCHMARK_SYMBOLS,
    )


# ── technical features (computed locally from equity_prices) ──────────────────


def _recompute_history(symbols: list[str], batch_size: int) -> int:
    """Rebuild these tickers' ENTIRE feature history from their current prices.
    Every rolling window (SMA-200, 252d return, OBV) depends on the full series,
    so a re-adjusted price invalidates the whole history, not just recent rows."""
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
    if technical_features_repo.is_empty():
        print("Technical features: no base data")
        return

    # Two distinct repairs. Features computed from prices Sharadar has since
    # re-adjusted are present but WRONG, so the missing-date scan below is blind
    # to them — they have to be rebuilt from scratch first.
    stale = technical_features_repo.get_stale_feature_tickers()
    if stale:
        rebuilt = _recompute_history(stale, batch_size)
        print(
            f"Technical features: rebuilt {rebuilt:,} rows for "
            f"{len(stale):,} re-adjusted tickers"
        )

    missing = technical_features_repo.get_missing_feature_dates()
    if stale:
        # The full rebuild above already covered these tickers end to end.
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


# ── fundamentals / ownership / events (all tickers, by date) ───────────────────


def update_fundamentals(sh: SharadarData):
    # SF1 *does* expose `lastupdated` as a filter, and it is the only cursor that
    # sees restatements: a 10-K/A filed today amending FY2019 carries
    # calendardate=2019-12-31, so a recent-calendardate window can never contain
    # it. Dropping the per-dimension loop also means MRQ/MRT/MRY get refreshed
    # instead of only the as-reported three, and the delta is a few dozen rows.
    _fetch(
        sh.fundamentals,
        fundamentals_repo.insert,
        "Fundamentals",
        lastupdated_since=fundamentals_repo.get_sync_cursor() or _lookback(90),
    )


# SF2/SF3/EVENTS expose no `lastupdated`, so these three can only window on the
# row's own date. The window is relative to TODAY rather than to what we hold,
# so skipping runs for longer than the window loses that data permanently.
def update_insider(sh: SharadarData):
    _fetch(
        sh.insider_transactions,
        insider_repo.insert,
        "Insider",
        start_date=_lookback(14),
        end_date=TODAY,
    )


def update_institutional(sh: SharadarData):
    _fetch(
        sh.institutional_holdings,
        institutional_repo.insert,
        "Institutional",
        start_date=_lookback(60),
        end_date=TODAY,
    )


def update_events(sh: SharadarData):
    _fetch(
        sh.events,
        event_repo.insert,
        "Events",
        start_date=_lookback(7),
        end_date=TODAY,
    )


# ── descriptors + macro ────────────────────────────────────────────────────────


def update_tickers(sh: SharadarData):
    # Include delisted — the descriptor table must know names that have died so
    # historical/point-in-time lookups can resolve them. `lastupdated` turns the
    # daily full-table re-upsert (~22k rows) into the handful that actually
    # changed; the resulting state is identical either way.
    # A None cursor (empty table) falls through as an unfiltered full fetch.
    since = tickers_repo.get_sync_cursor()
    equities = sh.tickers(table="SEP", lastupdated_since=since)
    funds = sh.tickers(table="SFP", tickers=BENCHMARK_SYMBOLS, lastupdated_since=since)
    df = pd.concat([equities, funds], ignore_index=True)
    if df.empty:
        print("Tickers: up to date")
        return
    tickers_repo.insert(df)
    print(f"Tickers: {len(df):,} upserted")


def update_macro():
    since = macro_repo.get_latest_dates() or "2021-01-01"
    df = MacroData().get_macro(since, TODAY)
    if df.empty:
        print("Macro: up to date")
        return
    macro_repo.insert(df)
    print(f"Macro: {len(df):,} new rows")


if __name__ == "__main__":
    print(f"=== QuorumNexus daily update — {TODAY} ===")
    sh = SharadarData()

    update_equity_prices(sh)
    update_fund_prices(sh)
    update_technical_features()
    update_fundamentals(sh)
    update_insider(sh)
    update_events(sh)
    update_macro()

    # Slower cadence but upsert-safe to run daily
    update_tickers(sh)
    update_institutional(sh)

    print("=== Done ===")
