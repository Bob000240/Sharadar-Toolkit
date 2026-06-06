import database.fundamentals_repository as fundamentals_repo
import database.sector_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:+.1%}"


def _rank(v: float | None) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:.0f}th percentile"


@dataclass
class GrowthSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Revenue growth
    revenue_growth_yoy: float | None
    revenue_growth_qoq: float | None
    revenue_vs_sector_growth: float | None   # computed cross-sectionally in model

    # EPS growth
    eps_growth_yoy: float | None
    eps_growth_qoq: float | None

    # Growth quality
    growth_consistency_score: float | None   # fraction of years with positive revenue growth

    # Universe-relative ranks (0–100)
    revenue_growth_percentile: float
    eps_growth_percentile: float

    # Composite
    growth_composite_percentile: float

    report_sections: list[str]

    def _fmt_header(self) -> str:
        return "\n".join([
            f"GROWTH ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Growth composite rank: {_rank(self.growth_composite_percentile)}"
            f"  (avg of revenue and EPS growth percentiles)",
        ])

    def _fmt_revenue_growth(self) -> str:
        if self.revenue_vs_sector_growth is not None and self.revenue_vs_sector_growth == self.revenue_vs_sector_growth:
            sector_note = "outpacing sector" if self.revenue_vs_sector_growth > 0 else "lagging sector"
            vs_sector = f"{_pct(self.revenue_vs_sector_growth)}  ({sector_note})"
        else:
            vs_sector = "N/A"
        return "\n".join([
            "--- REVENUE GROWTH ---",
            f"  Year-over-year:       {_pct(self.revenue_growth_yoy)}"
            f"   (universe rank: {_rank(self.revenue_growth_percentile)})",
            f"  Quarter-over-quarter: {_pct(self.revenue_growth_qoq)}   (sequential momentum)",
            f"  Vs sector average:    {vs_sector}",
        ])

    def _fmt_eps_growth(self) -> str:
        return "\n".join([
            "--- EPS GROWTH ---",
            f"  Year-over-year:       {_pct(self.eps_growth_yoy)}"
            f"   (universe rank: {_rank(self.eps_growth_percentile)})",
            f"  Quarter-over-quarter: {_pct(self.eps_growth_qoq)}   (sequential momentum)",
        ])

    def _fmt_growth_quality(self) -> str:
        if self.growth_consistency_score is not None and self.growth_consistency_score == self.growth_consistency_score:
            pct_positive = self.growth_consistency_score
            note = "strong" if pct_positive >= 0.75 else ("moderate" if pct_positive >= 0.5 else "weak")
            score_str = f"{pct_positive:.0%} of years positive  ({note})"
        else:
            score_str = "N/A  (insufficient history)"
        return "\n".join([
            "--- GROWTH QUALITY ---",
            f"  Revenue growth consistency: {score_str}",
        ])

    def to_agent_prompt(self) -> str:
        prompt_sections = {
            "revenue_growth": self._fmt_revenue_growth(),
            "eps_growth": self._fmt_eps_growth(),
            "growth_quality": self._fmt_growth_quality(),
        }

        try:
            return "\n\n".join([
                self._fmt_header(),
                *(prompt_sections[section] for section in self.report_sections if section in prompt_sections)
            ])
        except Exception as e:
            print(f"Error building prompt: {e}")
            print("Falling back to full report.")
            return "\n\n".join([
                self._fmt_header(),
                self._fmt_revenue_growth(),
                self._fmt_eps_growth(),
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

        fundamentals   = fundamentals.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        fundamentals["sector"] = sector_mapping["sector"]

        sector_avg = fundamentals.groupby("sector")["revenue_growth_yoy"].transform("mean")
        fundamentals["revenue_vs_sector_growth"] = (
            fundamentals["revenue_growth_yoy"] - sector_avg
        )

        all_annual = fundamentals_repo.get_growth(self.stock_symbols)
        all_annual = all_annual[all_annual["period"] == "annual"]

        def _consistency(group: pd.DataFrame) -> float | None:
            vals = group["revenue_growth_yoy"].dropna()
            if len(vals) < 2:
                return None
            return float((vals > 0).mean())

        consistency = (
            all_annual.groupby("symbol")
            .apply(_consistency, include_groups=False)
            .rename("growth_consistency_score")
        )
        fundamentals = fundamentals.join(consistency)

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

    def _get(self, symbol: str, col: str):
        v = self.stock_data.loc[symbol, col]
        return None if pd.isna(v) else v

    def build_snapshot(self, symbol: str, report_sections: list[str] | str) -> GrowthSnapshot:
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        return GrowthSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self._get(symbol, "sector"),
            revenue_growth_yoy=self._get(symbol, "revenue_growth_yoy"),
            revenue_growth_qoq=self._get(symbol, "revenue_growth_qoq"),
            revenue_vs_sector_growth=self._get(symbol, "revenue_vs_sector_growth"),
            eps_growth_yoy=self._get(symbol, "eps_growth_yoy"),
            eps_growth_qoq=self._get(symbol, "eps_growth_qoq"),
            growth_consistency_score=self._get(symbol, "growth_consistency_score"),
            revenue_growth_percentile=self._get(symbol, "revenue_growth_percentile"),
            eps_growth_percentile=self._get(symbol, "eps_growth_percentile"),
            growth_composite_percentile=self._get(symbol, "growth_composite_percentile"),
            report_sections=report_sections if isinstance(report_sections, list) else [report_sections],
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = GrowthFactorsModel(signal_day, symbols)
    report_sections = [
        "revenue_growth",
        "eps_growth",
        "growth_quality",
    ]
    for sym in symbols:
        print(model.build_snapshot(sym, report_sections).to_agent_prompt())
        print()
