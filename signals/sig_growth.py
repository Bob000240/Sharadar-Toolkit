import database.fundamentals_repository as fundamentals_repo
import database.sector_data_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class GrowthSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Revenue growth
    revenue_growth_yoy: float
    revenue_growth_qoq: float
    revenue_vs_sector_growth: float     # stock YoY revenue growth minus sector avg

    # EPS growth
    eps_growth_yoy: float
    eps_growth_qoq: float

    # Estimate revisions
    eps_revision_3m: float      # change in consensus EPS estimate over last 3 months

    # Growth quality
    growth_consistency_score: float     # 0–1; higher = more consistent multi-year growth

    # Universe-relative ranks (0–100)
    revenue_growth_percentile: float
    eps_growth_percentile:     float

    # Composite
    growth_composite_percentile: float

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    @staticmethod
    def _rank(v: float) -> str:
        return f"{v:.0f}th percentile"

    def _fmt_header(self) -> str:
        return "\n".join([
            f"GROWTH ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Growth composite rank: {self._rank(self.growth_composite_percentile)}  (avg of revenue and EPS growth percentiles)",
        ])

    def _fmt_revenue_growth(self) -> str:
        sector_note = (
            "outpacing sector" if self.revenue_vs_sector_growth > 0 else "lagging sector"
        )
        return "\n".join([
            "--- REVENUE GROWTH ---",
            f"  Year-over-year:          {self._pct(self.revenue_growth_yoy)}   (universe rank: {self._rank(self.revenue_growth_percentile)})",
            f"  Quarter-over-quarter:    {self._pct(self.revenue_growth_qoq)}   (sequential momentum)",
            f"  Vs sector average:       {self._pct(self.revenue_vs_sector_growth)}   ({sector_note})",
        ])

    def _fmt_eps_growth(self) -> str:
        return "\n".join([
            "--- EPS GROWTH ---",
            f"  Year-over-year:          {self._pct(self.eps_growth_yoy)}   (universe rank: {self._rank(self.eps_growth_percentile)})",
            f"  Quarter-over-quarter:    {self._pct(self.eps_growth_qoq)}   (sequential momentum)",
        ])

    def _fmt_estimate_revisions(self) -> str:
        direction = "rising" if self.eps_revision_3m > 0 else "falling"
        return "\n".join([
            "--- ESTIMATE REVISIONS ---",
            f"  Consensus EPS revision (3m): {self._pct(self.eps_revision_3m)}  ({direction}; positive = analysts upgrading expectations)",
        ])

    def _fmt_growth_quality(self) -> str:
        consistency_note = (
            "strong" if self.growth_consistency_score >= 0.7
            else ("moderate" if self.growth_consistency_score >= 0.4 else "weak")
        )
        return "\n".join([
            "--- GROWTH QUALITY ---",
            f"  Consistency score:  {self.growth_consistency_score:.2f}  ({consistency_note}; 0=erratic, 1=perfectly consistent multi-year growth)",
        ])

    def to_agent_prompt(self) -> str:
        return "\n\n".join([
            self._fmt_header(),
            self._fmt_revenue_growth(),
            self._fmt_eps_growth(),
            self._fmt_estimate_revisions(),
            self._fmt_growth_quality(),
        ])


class GrowthFactorsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str] | str,
    ):
        self.signal_day = signal_day
        self.stock_symbols = [stock_symbols] if isinstance(stock_symbols, str) else stock_symbols
        self.stock_data = None
        self._load_data()

    def _load_data(self):
        fundamentals = fundamentals_repo.get_latest_fundamentals(
            self.stock_symbols, self.signal_day
        )
        sector_mapping = sector_repo.get_sector_mapping(self.stock_symbols)

        fundamentals = fundamentals.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        fundamentals["sector"] = sector_mapping["sector"]

        for col in ["revenue_growth_yoy", "eps_growth_yoy"]:
            fundamentals[f"{col.replace('_yoy','')}_percentile"] = (
                fundamentals[col].rank(pct=True) * 100
            )

        fundamentals["revenue_growth_percentile"] = (
            fundamentals["revenue_growth_yoy"].rank(pct=True) * 100
        )
        fundamentals["eps_growth_percentile"] = (
            fundamentals["eps_growth_yoy"].rank(pct=True) * 100
        )
        fundamentals["growth_composite_percentile"] = (
            fundamentals["revenue_growth_percentile"]
            + fundamentals["eps_growth_percentile"]
        ) / 2

        self.stock_data = fundamentals

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> GrowthSnapshot:
        return GrowthSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self.get(symbol, "sector"),
            revenue_growth_yoy=self.get(symbol, "revenue_growth_yoy"),
            revenue_growth_qoq=self.get(symbol, "revenue_growth_qoq"),
            revenue_vs_sector_growth=self.get(symbol, "revenue_vs_sector_growth"),
            eps_growth_yoy=self.get(symbol, "eps_growth_yoy"),
            eps_growth_qoq=self.get(symbol, "eps_growth_qoq"),
            eps_revision_3m=self.get(symbol, "eps_revision_3m"),
            growth_consistency_score=self.get(symbol, "growth_consistency_score"),
            revenue_growth_percentile=self.get(symbol, "revenue_growth_percentile"),
            eps_growth_percentile=self.get(symbol, "eps_growth_percentile"),
            growth_composite_percentile=self.get(symbol, "growth_composite_percentile"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = GrowthFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
