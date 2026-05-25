import database.indicator_repository as indicator_repo
import database.sector_data_repository as sector_repo
import database.market_data_repository as market_repo

import pandas as pd
from dataclasses import dataclass

@dataclass
class QualitySnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Composite
    quality_composite_score: float    # 0-100 percentile rank

    # Profitability
    roe: float
    roa: float
    roic: float
    gross_margin: float
    operating_margin: float
    fcf_margin: float
    gross_margin_chg: float
    operating_margin_chg: float

    # Revenue
    revenue_growth_1y: float
    revenue_growth_3y: float          # 3y CAGR

    # Free cash flow
    fcf_yield: float
    fcf_growth_1y: float

    # Balance sheet
    debt_to_equity: float
    current_ratio: float
    interest_coverage: float

    # Earnings quality
    accruals_ratio: float
    earnings_consistency: float

    # Earnings revisions
    eps_revision_4w: float
    rev_revision_4w: float
    revision_breadth: float
    eps_revision_momentum: float      # acceleration
    eps_surprise_last_q: float

    # Valuation
    pe_ratio: float
    pb_ratio: float
    ev_to_ebitda: float
    pe_percentile: float              # within sector
    ev_ebitda_percentile: float       # within sector

    def to_agent_prompt(self) -> str:
        def pct(v: float) -> str:
            return f"{v:+.1%}"

        def pp(v: float) -> str:
            return f"{v:+.1f}pp"

        def ratio(v: float) -> str:
            return f"{v:.2f}x"

        def quality_label(score: float) -> str:
            if score >= 70: return "high quality"
            if score >= 40: return "average quality"
            return "low quality"

        def accruals_label(v: float) -> str:
            if v < -0.05: return "high quality — cash exceeds reported income"
            if v < 0.05:  return "average"
            return "low quality — accrual-heavy earnings"

        def valuation_label(percentile: float) -> str:
            if percentile > 70: return "expensive vs sector"
            if percentile > 30: return "fair vs sector"
            return "cheap vs sector"

        lines = [
            f"QUALITY ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            "",
            "--- QUALITY COMPOSITE ---",
            f"  Overall quality rank: {self.quality_composite_score:.0f}th percentile  "
            f"({quality_label(self.quality_composite_score)})",
            "",
            "--- PROFITABILITY ---",
            f"  ROE:              {pct(self.roe)}",
            f"  ROA:              {pct(self.roa)}",
            f"  ROIC:             {pct(self.roic)}  (core quality signal — return on invested capital)",
            f"  Gross margin:     {pct(self.gross_margin)}  (YoY change: {pp(self.gross_margin_chg)})",
            f"  Operating margin: {pct(self.operating_margin)}  (YoY change: {pp(self.operating_margin_chg)})",
            f"  FCF margin:       {pct(self.fcf_margin)}",
            "",
            "--- REVENUE ---",
            f"  Revenue growth (1y):      {pct(self.revenue_growth_1y)}",
            f"  Revenue growth (3y CAGR): {pct(self.revenue_growth_3y)}",
            "",
            "--- FREE CASH FLOW ---",
            f"  FCF yield:   {pct(self.fcf_yield)}  (higher = more cash generated per dollar of price)",
            f"  FCF growth:  {pct(self.fcf_growth_1y)} YoY",
            "",
            "--- BALANCE SHEET ---",
            f"  Debt / equity:      {ratio(self.debt_to_equity)}",
            f"  Current ratio:      {ratio(self.current_ratio)}  (>1.0 = can cover short-term liabilities)",
            f"  Interest coverage:  {ratio(self.interest_coverage)}x  (higher = more comfortable debt service)",
            "",
            "--- EARNINGS QUALITY ---",
            f"  Accruals ratio:       {self.accruals_ratio:+.3f}  ({accruals_label(self.accruals_ratio)})",
            f"  Earnings consistency: {self.earnings_consistency:.0%}  (positive EPS quarters / trailing 8Q)",
            "",
            "--- EARNINGS REVISIONS ---",
            f"  EPS revision (4w):       {pct(self.eps_revision_4w)}  "
            f"(positive = analysts raising estimates)",
            f"  Revenue revision (4w):   {pct(self.rev_revision_4w)}",
            f"  Revision breadth:        {self.revision_breadth:.0%}  "
            f"(fraction of analysts raising EPS)",
            f"  Revision momentum:       {pct(self.eps_revision_momentum)}  "
            f"(positive = revisions accelerating — more upgrades likely)",
            f"  Last-quarter EPS beat:   {pct(self.eps_surprise_last_q)}  "
            f"(positive = beat consensus)",
            "",
            "--- VALUATION ---",
            f"  P/E:        {ratio(self.pe_ratio)}  "
            f"({self.pe_percentile:.0f}th percentile — {valuation_label(self.pe_percentile)})",
            f"  P/B:        {ratio(self.pb_ratio)}",
            f"  EV/EBITDA:  {ratio(self.ev_to_ebitda)}  "
            f"({self.ev_ebitda_percentile:.0f}th percentile — {valuation_label(self.ev_ebitda_percentile)})",
        ]
        return "\n".join(lines)