"""
sig_fundamentals — quality, value, and growth signals from Sharadar SF1.

Reads from the unified `fundamentals` table (date_key = filing date for
point-in-time safety) and computes percentile ranks across the universe.

Signal domains:
  - Quality: ROE, ROA, ROIC, margins, leverage, cash conversion
  - Value:   P/E, P/B, P/S, EV/EBITDA, FCF yield (cross-referenced with DAILY table)
  - Growth:  YoY revenue / EPS growth computed from sequential SF1 rows
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np
import database.fundamentals_repository as fund_repo
import database.market_metrics_repository as mm_repo


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class FundamentalsSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    date_key: pd.Timestamp | None      # filing date used (for audit)

    # Quality
    roe: float | None
    roa: float | None
    roic: float | None
    gross_margin: float | None
    ebitda_margin: float | None
    net_margin: float | None
    fcf_margin: float | None
    current_ratio: float | None
    debt_to_equity: float | None
    interest_coverage: float | None
    piotroski: int | None

    # Value (from SF1 or DAILY table)
    pe: float | None
    pb: float | None
    ps: float | None
    ev_ebitda: float | None

    # Growth (computed from sequential ARQ rows)
    revenue_growth_yoy: float | None
    eps_growth_yoy: float | None

    # Universe percentile ranks (0–100)
    roe_pct: float | None
    roic_pct: float | None
    net_margin_pct: float | None
    pe_pct: float | None         # lower PE = better value = higher rank
    ev_ebitda_pct: float | None  # lower = better
    revenue_growth_pct: float | None
    eps_growth_pct: float | None

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class FundamentalsModel:
    """
    Loads SF1 fundamentals for a universe of tickers as of signal_day.
    Computes universe percentile ranks and exposes per-ticker snapshots.

    Usage:
        model = FundamentalsModel(signal_day, stock_symbols)
        snap  = model.build_snapshot("AAPL")
    """

    def __init__(self, signal_day: pd.Timestamp, stock_symbols: list[str]):
        self.signal_day = signal_day
        self.tickers = stock_symbols
        self._df: pd.DataFrame = pd.DataFrame()
        self._daily: pd.DataFrame = pd.DataFrame()
        self._load()

    def _load(self) -> None:
        day = self.signal_day.date() if hasattr(self.signal_day, "date") else self.signal_day

        # Load most-recent ARQ (quarterly) row per ticker — best data density
        ary = fund_repo.get_fundamentals(self.tickers, dimension="ARY", as_of=day)
        arq = fund_repo.get_fundamentals(self.tickers, dimension="ARQ", as_of=day)

        # Prefer ARQ for growth computations; use ARY as fallback for annual ratios
        # Merge: ARQ wins on ratio columns if available
        if not arq.empty and not ary.empty:
            base = ary.set_index("ticker")
            quarterly = arq.set_index("ticker")
            ratio_cols = ["roe", "roa", "roic", "gross_margin", "ebitda_margin",
                          "net_margin", "fcf_margin", "current_ratio", "debt_to_equity",
                          "interest_coverage", "piotroski"]
            for col in ratio_cols:
                if col in quarterly.columns and col in base.columns:
                    base[col] = quarterly[col].combine_first(base[col])
            df = base.reset_index()
        elif not arq.empty:
            df = arq
        else:
            df = ary

        self._df = df.set_index("ticker") if not df.empty else pd.DataFrame()

        # Load DAILY metrics for market valuation multiples
        try:
            self._daily = mm_repo.get_daily(self.tickers, as_of=day)
            if not self._daily.empty and "ticker" in self._daily.columns:
                self._daily = self._daily.set_index("ticker")
        except Exception:
            self._daily = pd.DataFrame()

        # Compute YoY growth from sequential ARQ rows
        self._growth = self._compute_growth(day)

        # Compute universe percentile ranks
        self._ranks = self._compute_ranks()

    def _compute_growth(self, as_of) -> pd.DataFrame:
        """Load last two ARQ rows per ticker and compute YoY growth."""
        try:
            series = fund_repo.get_fundamentals_series(
                self.tickers, "ARQ",
                start=str(pd.Timestamp(as_of) - pd.DateOffset(years=2)),
                end=str(as_of),
            )
        except Exception:
            return pd.DataFrame()

        if series.empty or "ticker" not in series.columns:
            return pd.DataFrame()

        rows = []
        for ticker, grp in series.groupby("ticker"):
            grp = grp.sort_values("date_key")
            if len(grp) < 5:    # need at least 5 quarters for reliable YoY
                continue
            latest = grp.iloc[-1]
            year_ago = grp.iloc[-5] if len(grp) >= 5 else None
            if year_ago is None:
                continue
            rev_now = latest.get("revenue")
            rev_ago = year_ago.get("revenue")
            eps_now = latest.get("eps_diluted")
            eps_ago = year_ago.get("eps_diluted")
            rows.append({
                "ticker": ticker,
                "revenue_growth_yoy": (rev_now - rev_ago) / abs(rev_ago)
                    if rev_now and rev_ago and rev_ago != 0 else None,
                "eps_growth_yoy": (eps_now - eps_ago) / abs(eps_ago)
                    if eps_now and eps_ago and eps_ago != 0 else None,
            })
        return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()

    def _rank(self, series: pd.Series, ascending: bool = False) -> pd.Series:
        return series.rank(pct=True, ascending=ascending, na_option="keep") * 100

    def _compute_ranks(self) -> pd.DataFrame:
        if self._df.empty:
            return pd.DataFrame()
        ranks: dict[str, pd.Series] = {}
        for col, asc in [("roe", False), ("roic", False), ("net_margin", False)]:
            if col in self._df.columns:
                ranks[f"{col}_pct"] = self._rank(self._df[col], ascending=asc)
        # For valuation, lower = better value = higher rank → ascending=True
        for col in ["pe", "pb", "ev_ebitda"]:
            daily_col = col
            if not self._daily.empty and daily_col in self._daily.columns:
                ranks[f"{daily_col}_pct"] = self._rank(self._daily[daily_col], ascending=True)
        if not self._growth.empty:
            if "revenue_growth_yoy" in self._growth.columns:
                ranks["revenue_growth_pct"] = self._rank(self._growth["revenue_growth_yoy"], ascending=False)
            if "eps_growth_yoy" in self._growth.columns:
                ranks["eps_growth_pct"] = self._rank(self._growth["eps_growth_yoy"], ascending=False)
        return pd.DataFrame(ranks)

    def _get(self, ticker: str, col: str, source: pd.DataFrame | None = None) -> float | None:
        df = source if source is not None else self._df
        if df.empty or ticker not in df.index or col not in df.columns:
            return None
        v = df.loc[ticker, col]
        return None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

    def build_snapshot(self, ticker: str) -> FundamentalsSnapshot:
        date_key_raw = self._get(ticker, "date_key")
        date_key = pd.Timestamp(date_key_raw) if date_key_raw else None

        growth_rev = self._get(ticker, "revenue_growth_yoy", self._growth)
        growth_eps = self._get(ticker, "eps_growth_yoy", self._growth)

        return FundamentalsSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            date_key=date_key,
            # Quality
            roe=self._get(ticker, "roe"),
            roa=self._get(ticker, "roa"),
            roic=self._get(ticker, "roic"),
            gross_margin=self._get(ticker, "gross_margin"),
            ebitda_margin=self._get(ticker, "ebitda_margin"),
            net_margin=self._get(ticker, "net_margin"),
            fcf_margin=self._get(ticker, "fcf_margin"),
            current_ratio=self._get(ticker, "current_ratio"),
            debt_to_equity=self._get(ticker, "debt_to_equity"),
            interest_coverage=self._get(ticker, "interest_coverage"),
            piotroski=self._get(ticker, "piotroski"),
            # Value (prefer DAILY for market-cap-derived ratios)
            pe=self._get(ticker, "pe", self._daily) if not self._daily.empty else None,
            pb=self._get(ticker, "pb", self._daily) if not self._daily.empty else None,
            ps=self._get(ticker, "ps", self._daily) if not self._daily.empty else None,
            ev_ebitda=self._get(ticker, "evebitda", self._daily) if not self._daily.empty else None,
            # Growth
            revenue_growth_yoy=growth_rev,
            eps_growth_yoy=growth_eps,
            # Ranks
            roe_pct=self._get(ticker, "roe_pct", self._ranks),
            roic_pct=self._get(ticker, "roic_pct", self._ranks),
            net_margin_pct=self._get(ticker, "net_margin_pct", self._ranks),
            pe_pct=self._get(ticker, "pe_pct", self._ranks),
            ev_ebitda_pct=self._get(ticker, "ev_ebitda_pct", self._ranks),
            revenue_growth_pct=self._get(ticker, "revenue_growth_pct", self._ranks),
            eps_growth_pct=self._get(ticker, "eps_growth_pct", self._ranks),
        )
