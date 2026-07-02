"""
Daily incremental update. Run each market day after close.

    uv run python -m set_up.daily_update
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from set_up.config import get_stock_symbols, BENCHMARK_SYMBOLS
from set_up.load_data import START_DATE
from data.sharadar_data import SharadarData
from data.macro_data import MacroData
from data.indicators import compute_indicators

import database.market.equity_repo as equity_repo
import database.market.fund_repo as fund_repo
import database.market.indicators_repo as indicators_repo
import database.market.tickers_repo as tickers_repo
import database.market.fundamentals_repo as fundamentals_repo
import database.market.insider_repo as insider_repo
import database.market.institutional_repo as institutional_repo
import database.market.event_repo as event_repo
import database.market.macro_repo as macro_repo

TODAY = pd.Timestamp.today().strftime("%Y-%m-%d")


def _batched(
    sh_fn, repo_insert, label: str, symbols: list = None, batch_size: int = 50, **kwargs
):
    symbols = symbols if symbols is not None else get_stock_symbols()
    total = 0
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        df = sh_fn(tickers=batch, **kwargs)
        if not df.empty:
            repo_insert(df)
            total += len(df)
    print(f"{label}: {total:,} rows upserted")


def _update_prices_split(sh_fn, repo_insert, repo_get_latest, label: str, symbols: list):
    """Fetch each ticker only from ITS OWN last-loaded date forward; tickers new to
    the table get a full backfill. Tickers that share a last date are grouped into
    the same API call.

    This is the fix for the min()-pins-everyone problem: previously `since` was a
    single date derived from the *earliest* last-date across the universe, so a
    couple of laggard tickers forced a full-window re-fetch for all ~2,400 names
    (most of which already had the data — silently discarded by ON CONFLICT DO
    NOTHING, but still fetched over the network). Here, names already current fetch
    nothing, and only genuine gaps are pulled — so the fetched row count is also
    honest, since every fetched row is strictly newer than what's stored."""
    latest = repo_get_latest(tickers=symbols)
    last_by_ticker = (
        dict(zip(latest["ticker"], latest["latest_date"])) if not latest.empty else {}
    )

    # New tickers (no rows yet) → full backfill from inception.
    new = [t for t in symbols if t not in last_by_ticker]
    if new:
        _batched(
            sh_fn,
            repo_insert,
            f"{label} (new, backfill {len(new)} tickers)",
            symbols=new,
            start_date=START_DATE,
            end_date=TODAY,
        )

    # Known tickers → group by their own next-needed date; skip any already current.
    by_since: dict[str, list[str]] = {}
    for t in symbols:
        last = last_by_ticker.get(t)
        if last is None:
            continue
        since = str(last + pd.Timedelta(days=1))
        if since > TODAY:
            continue  # already up to date — fetch nothing
        by_since.setdefault(since, []).append(t)

    for since, group in sorted(by_since.items()):
        _batched(
            sh_fn,
            repo_insert,
            f"{label} (from {since}, {len(group)} tickers)",
            symbols=group,
            start_date=since,
            end_date=TODAY,
        )


def update_equity_prices(sh: SharadarData):
    _update_prices_split(
        sh.equity_prices,
        equity_repo.insert,
        equity_repo.get_latest_date,
        "Equity prices",
        get_stock_symbols(),
    )


def update_fund_prices(sh: SharadarData):
    _update_prices_split(
        sh.fund_prices,
        fund_repo.insert,
        fund_repo.get_latest_date,
        "Fund prices",
        BENCHMARK_SYMBOLS,
    )


def update_indicators():
    latest = indicators_repo.get_latest_date()
    if latest.empty:
        print("Indicators: no base data")
        return
    latest_date = latest["latest_date"].min()
    lookback = pd.Timestamp(latest_date) - pd.Timedelta(days=400)
    symbols = get_stock_symbols()
    total = 0
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        df = equity_repo.get(tickers=batch, start_date=str(lookback.date()))
        if df.empty:
            continue
        parts = [
            compute_indicators(g.reset_index(drop=True))
            for _, g in df.sort_values(["ticker", "date"]).groupby("ticker", sort=False)
        ]
        ind_df = pd.concat(parts, ignore_index=True)
        new_rows = ind_df[ind_df["date"] > latest_date]
        if not new_rows.empty:
            indicators_repo.insert(new_rows)
            total += len(new_rows)
    print(f"Indicators: {total:,} new rows")


def update_fundamentals(sh: SharadarData):
    since = (pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    for dim in ("ARY", "ARQ", "ART"):
        _batched(
            sh.fundamentals,
            fundamentals_repo.insert,
            f"Fundamentals {dim}",
            dimension=dim,
            start_date=since,
        )


def update_insider(sh: SharadarData):
    since = (pd.Timestamp.today() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    _batched(sh.insider_transactions, insider_repo.insert, "Insider", start_date=since)


def update_institutional(sh: SharadarData):
    since = (pd.Timestamp.today() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    _batched(
        sh.institutional_holdings,
        institutional_repo.insert,
        "Institutional",
        start_date=since,
    )


def update_events(sh: SharadarData):
    since = (pd.Timestamp.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    _batched(sh.events, event_repo.insert, "Events", start_date=since)


def update_tickers(sh: SharadarData):
    equities = sh.tickers(table="SEP", is_delisted=False)
    funds = sh.tickers(table="SFP", tickers=BENCHMARK_SYMBOLS)
    df = pd.concat([equities, funds], ignore_index=True)
    tickers_repo.insert(df)
    print(f"Tickers: {len(df):,} upserted")


def update_macro():
    since = macro_repo.get_latest_date() or "2021-01-01"
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
    update_indicators()
    update_fundamentals(sh)
    update_insider(sh)
    update_events(sh)
    update_macro()

    # Slower cadence but upsert-safe to run daily
    update_tickers(sh)
    update_institutional(sh)

    print("=== Done ===")
