"""Entry-quality backtest harness.

Answers the necessary-condition question for any strategy: *do its picks beat the
market, across many signal dates, at the median?* — before you build exits, an
agent, or anything else on top of it.

It couples to a strategy through exactly one call: `screener.run(signal_day) ->
list[CandidateSnapshot]`. Everything else (forward returns, benchmarking,
aggregation) is strategy-agnostic price math, so the same harness measures any
strategy that honors that contract — pass a different screener, nothing else
changes.

This is the *entry* harness: it holds every pick a fixed horizon (a deliberately
dumb, constant exit) precisely so any difference in outcome is attributable to
the entry ranking, not to exit timing. A full-P&L harness that also calls the
ExitMonitor is a later, separate thing.

Point-in-time discipline:
  - entry = first close STRICTLY AFTER signal_day (you can't trade on the close
    you computed the signal from);
  - exit = last close on/before signal_day + horizon;
  - a name that stops trading in the window uses its last available close
    (captures the loss — no survivorship bias in the forward measurement);
  - (date, horizon) pairs whose exit would fall past the latest available price
    are skipped, so every reported return spans a full horizon.

Reporting is median- and hit-rate-first, never mean-first: a single moonshot
inflates the mean and hides that the typical pick only matched the market (the
lesson from the one-date check).
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

import database.source.equity_repo as equity_repo
import database.source.fund_repo as fund_repo
from database.db_connection import get_connection
from pipeline.config import ETF_SECTOR_MAP

# The 11 sector ETFs and the sector -> ETF lookup, from the one source of truth.
# Equal-weighting them gives a sector-neutral market benchmark (strips SPY's
# mega-cap-tech concentration); individually, each is its sector's natural
# benchmark for the per-sector "did our picks beat the sector" test.
_SECTOR_ETFS = list(ETF_SECTOR_MAP)
_SECTOR_TO_ETF = {sector: etf for etf, sector in ETF_SECTOR_MAP.items()}


def _latest_price_date() -> pd.Timestamp:
    row = pd.read_sql_query(
        text("SELECT MAX(date) AS d FROM equity_prices"), get_connection()
    )
    return pd.Timestamp(row["d"].iloc[0])


def _forward_returns(tickers, signal_day, exit_by, get_fn) -> pd.Series:
    """Per-ticker return from the first close after `signal_day` to the last close
    on/before `exit_by`. `get_fn` is equity_repo.get (stocks) or fund_repo.get
    (benchmark). Tickers without at least two closes in the window are dropped."""
    signal_day = pd.Timestamp(signal_day)
    prices = get_fn(
        tickers=list(tickers),
        start_date=str((signal_day + pd.Timedelta(days=1)).date()),
        end_date=str(pd.Timestamp(exit_by).date()),
    )
    if prices.empty:
        return pd.Series(dtype=float)

    prices = prices[prices["close"] > 0].copy()
    prices["date"] = pd.to_datetime(prices["date"])
    out = {}
    for ticker, group in prices.sort_values("date").groupby("ticker"):
        closes = group["close"].to_numpy()
        if len(closes) >= 2:
            out[ticker] = closes[-1] / closes[0] - 1
    return pd.Series(out, dtype=float)


def backtest(
    screener,
    dates,
    horizons_months=(6, 12),
    benchmark="SPY",
    benchmark_label=None,
    eligible_fn=None,
) -> pd.DataFrame:
    """Run `screener` on each of `dates`, forward-return its menu at each horizon.

    `benchmark` is a single fund ticker ("SPY", cap-weight market) or a list of
    fund tickers, in which case it's held equal-weight — e.g. the 11 sector ETFs
    give a sector-neutral market that strips out SPY's mega-cap-tech concentration,
    a fairer yardstick for a sector-diversified mid-cap strategy. `benchmark_label`
    names it in the output (defaults to the ticker, or "EW[<n>]" for a basket).

    `eligible_fn(signal_day) -> list[str]` is optional: if given, the harness also
    forward-returns the strategy's whole eligible universe, which decomposes the
    edge — universe-vs-market is the *prefilter's* value, menu-vs-universe is the
    *ranking's* value. Omit it and only the menu-vs-market comparison is reported.

    Returns `(pooled, per_sector)` — one row per (date, horizon) for the whole
    menu, and one row per (date, horizon, sector) comparing that sector's picks to
    its own ETF. Feed them to `summarize()` and `summarize_sectors()`.
    """
    bench_tickers = [benchmark] if isinstance(benchmark, str) else list(benchmark)
    if benchmark_label is None:
        benchmark_label = (
            bench_tickers[0] if len(bench_tickers) == 1 else f"EW[{len(bench_tickers)}]"
        )

    latest = _latest_price_date()
    records = []
    sector_records = []

    for signal_day in dates:
        signal_day = pd.Timestamp(signal_day)
        menu = screener.run(signal_day)
        if not menu:
            continue
        scores = pd.Series({c.symbol: c.setup_score for c in menu})
        pick_sector = {c.symbol: c.signal_context["sector"] for c in menu}
        universe = eligible_fn(signal_day) if eligible_fn else None

        for months in horizons_months:
            exit_by = signal_day + pd.DateOffset(months=months)
            if exit_by > latest:
                continue  # not enough forward data for a full horizon

            menu_ret = _forward_returns(scores.index, signal_day, exit_by, equity_repo.get)
            if menu_ret.empty:
                continue
            # equal-weight the benchmark basket (a single ticker averages to itself)
            bench_ret = _forward_returns(
                bench_tickers, signal_day, exit_by, fund_repo.get
            ).mean()

            # within-menu ranking skill for this date (weak test: the menu is
            # already the pre-selected top slice, so score dispersion is small)
            paired = pd.DataFrame({"score": scores, "ret": menu_ret}).dropna()
            rho = (
                paired["score"].corr(paired["ret"], method="spearman")
                if len(paired) > 3
                else np.nan
            )

            record = {
                "date": signal_day.date(),
                "horizon_m": months,
                "n": int(len(menu_ret)),
                "menu_median": menu_ret.median(),
                "menu_mean": menu_ret.mean(),
                "menu_hit": (menu_ret > 0).mean(),
                "benchmark": bench_ret,
                "benchmark_label": benchmark_label,
                "score_rho": rho,
            }
            if universe is not None:
                univ_ret = _forward_returns(universe, signal_day, exit_by, equity_repo.get)
                record["universe_median"] = univ_ret.median()
            records.append(record)

            # per-sector: each sector's picks vs its own ETF (sector-relative
            # alpha — strips out which sector was hot, isolates pick quality).
            etf_ret = _forward_returns(_SECTOR_ETFS, signal_day, exit_by, fund_repo.get)
            for sector, etf in _SECTOR_TO_ETF.items():
                picks = [s for s in menu_ret.index if pick_sector.get(s) == sector]
                if not picks or etf not in etf_ret.index:
                    continue
                picks_median = menu_ret[picks].median()
                sector_records.append(
                    {
                        "date": signal_day.date(),
                        "horizon_m": months,
                        "sector": sector,
                        "n_picks": len(picks),
                        "picks_median": picks_median,
                        "etf_return": etf_ret[etf],
                        "alpha": picks_median - etf_ret[etf],
                    }
                )

    return pd.DataFrame(records), pd.DataFrame(sector_records)


def summarize(results: pd.DataFrame) -> None:
    """Print the cross-date aggregate per horizon. Median-first, benchmark-relative."""
    if results.empty:
        print("no completed (date, horizon) pairs — check the date range vs data end")
        return

    bench_name = results["benchmark_label"].iloc[0]

    has_universe = "universe_median" in results.columns
    for months, group in results.groupby("horizon_m"):
        print(f"\n=== {months}-month horizon  ({len(group)} signal dates) ===")
        print(f"  menu median return    : {group['menu_median'].median():+7.1%}   (median across dates)")
        print(f"  menu mean return      : {group['menu_mean'].median():+7.1%}   (mean is tail-inflated — compare)")
        print(f"  benchmark ({bench_name}) med : {group['benchmark'].median():+7.1%}")
        print(f"  menu beat benchmark   : {(group['menu_median'] > group['benchmark']).mean():.0%} of dates")
        print(f"  menu hit rate         : {group['menu_hit'].mean():.0%}")
        if has_universe:
            print(f"  eligible-universe med : {group['universe_median'].median():+7.1%}   [prefilter value vs market]")
            edge = (group["menu_median"] - group["universe_median"]).median()
            print(f"  menu minus universe   : {edge:+7.1%}   [ranking value — is the score worth anything?]")
        print(f"  score->return rho     : {group['score_rho'].mean():+.3f}   (avg per-date within menu; ~0 = no skill)")


def summarize_sectors(sector_results: pd.DataFrame, horizon: int = 12) -> None:
    """Per-sector picks-vs-ETF alpha, aggregated across dates at one horizon.
    Sorted best-to-worst by median alpha: shows where the strategy earns its keep
    and where it drags — the heterogeneity the pooled result averages away."""
    if sector_results.empty:
        print("no per-sector records")
        return
    group = sector_results[sector_results["horizon_m"] == horizon]
    if group.empty:
        print(f"no per-sector records at the {horizon}-month horizon")
        return

    agg = (
        group.groupby("sector")
        .agg(
            dates=("date", "nunique"),
            picks=("picks_median", "median"),
            etf=("etf_return", "median"),
            alpha=("alpha", "median"),
            beat=("alpha", lambda a: (a > 0).mean()),
        )
        .sort_values("alpha", ascending=False)
    )

    print(f"\n=== per-sector: picks vs sector ETF, {horizon}-month, median across dates ===")
    print(f"  {'sector':22s} {'picks':>7s} {'ETF':>7s} {'alpha':>7s} {'beat':>5s}  dates")
    for sector, row in agg.iterrows():
        print(
            f"  {sector:22s} {row['picks']:+6.1%} {row['etf']:+6.1%} "
            f"{row['alpha']:+6.1%} {row['beat']:5.0%}  {int(row['dates'])}"
        )
    print(f"  {'-' * 50}")
    print(f"  sectors with positive median alpha: "
          f"{int((agg['alpha'] > 0).sum())} / {len(agg)}")


if __name__ == "__main__":
    import sys

    import database.source.eligibility_repo as eligibility_repo
    from decision.strategies.strat_sector_leaders import SLEntryScreener

    # benchmark: "spy" (cap-weight) or "ew" (equal-weight sector ETFs, the default)
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "ew"
    benchmark = "SPY" if mode == "spy" else _SECTOR_ETFS
    label = "SPY" if mode == "spy" else "EW-sector"

    dates = pd.date_range("2020-01-01", "2025-01-01", freq="QS")
    print(f"backtesting sector_leaders over {len(dates)} quarterly dates "
          f"({dates[0].date()} -> {dates[-1].date()}), benchmark = {label}...")

    pooled, per_sector = backtest(
        SLEntryScreener(),
        dates,
        horizons_months=(6, 12),
        benchmark=benchmark,
        benchmark_label=label,
        eligible_fn=lambda d: eligibility_repo.SL_eligible_tickers(d)["ticker"].tolist(),
    )
    summarize(pooled)
    summarize_sectors(per_sector, horizon=12)
