"""
Daily incremental update. Run each market day after close.
    uv run python -m set_up.daily_update
"""

import pandas as pd
from set_up.config import BENCHMARK_SYMBOLS
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


def _lookback(days: int) -> str:
    return (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _fetch_all(sh_fn, repo_insert, label: str, start_date: str, **kwargs) -> None:
    """Fetch every ticker with data in [start_date, TODAY] (no ticker filter) and
    upsert. Sharadar paginates the full cross-section in one logical call."""
    df = sh_fn(start_date=start_date, end_date=TODAY, **kwargs)
    if df.empty:
        print(f"{label}: up to date")
        return
    repo_insert(df)
    print(f"{label}: {len(df):,} rows upserted")


# ── prices ────────────────────────────────────────────────────────────────────


def update_equity_prices(sh: SharadarData):
    latest = equity_repo.get_latest_dates()
    if latest.empty:
        _fetch_all(sh.equity_prices, equity_repo.insert, "Equity prices", START_DATE)
        return
    latest["latest_date"] = pd.to_datetime(latest["latest_date"])

    # Which tickers are still trading? A listed name gets a row every trading day,
    # so anything more than ~10 days behind the most recent data is delisted/halted
    # (no new data to fetch — and its old date must not drag the fetch back years).
    max_date = latest["latest_date"].max()
    active = latest[latest["latest_date"] >= max_date - pd.Timedelta(days=10)]

    # Start from the OLDEST active latest date, not the newest, so a ticker that's
    # behind isn't skipped — every active ticker gets every day after its own
    # latest date. One no-filter fetch covers them all; ON CONFLICT DO NOTHING
    # dedupes the recent days most tickers already have.
    since = (active["latest_date"].min() + pd.Timedelta(days=1)).date()
    if str(since) > TODAY:
        print("Equity prices: up to date")
        return
    df = sh.equity_prices(start_date=str(since), end_date=TODAY)
    if df.empty:
        print("Equity prices: up to date")
        return
    equity_repo.insert(df)
    print(f"Equity prices: {len(df):,} rows upserted (since {since})")


def update_fund_prices(sh: SharadarData):
    # Funds are a fixed curated set (benchmark + sector ETFs), not the equity
    # universe — fetch exactly those, incrementally.
    latest = fund_repo.get_latest_dates(tickers=BENCHMARK_SYMBOLS)
    since = (
        str(latest["latest_date"].max() + pd.Timedelta(days=1))
        if not latest.empty
        else START_DATE
    )
    if since > TODAY:
        print("Fund prices: up to date")
        return
    df = sh.fund_prices(tickers=BENCHMARK_SYMBOLS, start_date=since, end_date=TODAY)
    if df.empty:
        print("Fund prices: up to date")
        return
    fund_repo.insert(df)
    print(f"Fund prices: {len(df):,} rows upserted")


# ── indicators (computed locally from equity_prices) ───────────────────────────


def update_indicators(batch_size: int = 200):
    ind_latest = indicators_repo.get_latest_dates()
    if ind_latest.empty:
        print("Indicators: no base data")
        return
    missing = indicators_repo.get_missing_price_dates()
    if missing.empty:
        print("Indicators: up to date")
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
            ind = compute_indicators(g.reset_index(drop=True))
            ind["date"] = pd.to_datetime(ind["date"])
            wanted = ind["date"].isin(missing_dates[tk])
            new_parts.append(ind[wanted])
        new_rows = pd.concat(new_parts, ignore_index=True)
        if not new_rows.empty:
            indicators_repo.insert(new_rows)
            total += len(new_rows)
        print(f"  indicators batch {i // batch_size + 1}/{n_batches}  (+{total:,} rows)")
    print(f"Indicators: {total:,} new rows ({len(symbols):,} tickers)")


# ── fundamentals / ownership / events (all tickers, by date) ───────────────────


def update_fundamentals(sh: SharadarData):
    # calendardate lookback catches recent periods across all names (Sharadar's
    # fundamentals endpoint filters on calendardate, not lastupdated).
    since = _lookback(90)
    for dim in ("ARY", "ARQ", "ART"):
        _fetch_all(
            sh.fundamentals,
            fundamentals_repo.insert,
            f"Fundamentals {dim}",
            since,
            dimension=dim,
        )


def update_insider(sh: SharadarData):
    _fetch_all(
        sh.insider_transactions, insider_repo.insert, "Insider", _lookback(14)
    )


def update_institutional(sh: SharadarData):
    _fetch_all(
        sh.institutional_holdings,
        institutional_repo.insert,
        "Institutional",
        _lookback(60),
    )


def update_events(sh: SharadarData):
    _fetch_all(sh.events, event_repo.insert, "Events", _lookback(7))


# ── descriptors + macro ────────────────────────────────────────────────────────


def update_tickers(sh: SharadarData):
    # Include delisted — the descriptor table must know names that have died so
    # historical/point-in-time lookups can resolve them.
    equities = sh.tickers(table="SEP")
    funds = sh.tickers(table="SFP", tickers=BENCHMARK_SYMBOLS)
    df = pd.concat([equities, funds], ignore_index=True)
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
    update_indicators()
    update_fundamentals(sh)
    update_insider(sh)
    update_events(sh)
    update_macro()

    # Slower cadence but upsert-safe to run daily
    update_tickers(sh)
    update_institutional(sh)

    print("=== Done ===")
