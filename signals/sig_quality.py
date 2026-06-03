import database.fundamentals_repository as fundamentals_repo
import database.indicator_repository as indicator_repo
import database.sector_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:+.1%}"


def _x(v: float | None, fmt: str = ".1f") -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:{fmt}}x"


def _rank(v: float | None) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "N/A"
    return f"{v:.0f}th percentile"


@dataclass
class QualitySnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Profitability
    roe: float | None
    roa: float | None
    roic: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    fcf_margin: float | None

    # Cash quality
    cash_conversion: float | None
    accruals_ratio: float | None

    # Balance sheet
    debt_to_equity: float | None
    net_debt_to_ebitda: float | None
    interest_coverage: float | None   # None when company has net interest income
    current_ratio: float | None

    # Capital efficiency
    asset_turnover: float | None

    # Market risk (price-based)
    volatility_20: float
    atr_pct: float
    drawdown_from_recent_high: float

    # Universe-relative ranks (0–100)
    roe_percentile: float
    roic_percentile: float
    operating_margin_percentile: float
    fcf_margin_percentile: float

    # Composite
    quality_composite_percentile: float

    report_sections: list[str]

    def _fmt_header(self) -> str:
        return "\n".join([
            f"QUALITY ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Quality composite rank: {_rank(self.quality_composite_percentile)}"
            f"  (avg of ROE, ROIC, operating margin, FCF margin percentiles)",
        ])

    def _fmt_profitability(self) -> str:
        return "\n".join([
            "--- PROFITABILITY ---",
            f"  Return on equity (ROE):              {_pct(self.roe)}"
            f"   (universe rank: {_rank(self.roe_percentile)})",
            f"  Return on assets (ROA):              {_pct(self.roa)}",
            f"  Return on invested capital (ROIC):   {_pct(self.roic)}"
            f"   (universe rank: {_rank(self.roic_percentile)})",
            f"  Gross margin:                        {_pct(self.gross_margin)}",
            f"  Operating margin:                    {_pct(self.operating_margin)}"
            f"   (universe rank: {_rank(self.operating_margin_percentile)})",
            f"  Net margin:                          {_pct(self.net_margin)}",
            f"  Free cash flow margin:               {_pct(self.fcf_margin)}"
            f"   (universe rank: {_rank(self.fcf_margin_percentile)})",
        ])

    def _fmt_cash_quality(self) -> str:
        return "\n".join([
            "--- CASH QUALITY ---",
            f"  Cash conversion (FCF / net income):  {_x(self.cash_conversion, '.2f')}"
            f"  (>1.0 = earnings fully backed by cash)",
            f"  Accruals ratio:                      "
            f"{self.accruals_ratio:.3f}  (lower = higher quality; >0.1 = elevated concern)"
            if self.accruals_ratio is not None and self.accruals_ratio == self.accruals_ratio
            else "  Accruals ratio:                      N/A",
        ])

    def _fmt_balance_sheet(self) -> str:
        ic_str = (
            f"{self.interest_coverage:.1f}x  (>3x = debt burden manageable)"
            if self.interest_coverage is not None and self.interest_coverage == self.interest_coverage
            else "N/A  (net interest income — company earns more than it pays)"
        )
        nd_str = (
            f"{self.net_debt_to_ebitda:.2f}x  (<3x = conservative)"
            if self.net_debt_to_ebitda is not None and self.net_debt_to_ebitda == self.net_debt_to_ebitda
            else "N/A"
        )
        return "\n".join([
            "--- BALANCE SHEET STRENGTH ---",
            f"  Debt-to-equity:                {_x(self.debt_to_equity, '.2f')}  (<1.0 = conservative leverage)",
            f"  Net debt / EBITDA:             {nd_str}",
            f"  Interest coverage (EBIT/Int):  {ic_str}",
            f"  Current ratio:                 {_x(self.current_ratio, '.2f')}  (>1.0 = liquid)",
            f"  Asset turnover:                {_x(self.asset_turnover, '.2f')}  (higher = more efficient)",
        ])

    def _fmt_market_risk(self) -> str:
        drawdown_note = (
            "at recent peak"
            if self.drawdown_from_recent_high == 0
            else f"{self.drawdown_from_recent_high:.1%} off 20-day high"
        )
        return "\n".join([
            "--- MARKET RISK ---",
            f"  20-day realised volatility (ann.):  {self.volatility_20:.1%}",
            f"  ATR as % of price:                  {self.atr_pct:.2%}",
            f"  Drawdown from 20-day high:          {drawdown_note}",
        ])

    def to_agent_prompt(self) -> str:
        prompt_sections = {
            "profitability": self._fmt_profitability(),
            "cash_quality": self._fmt_cash_quality(),
            "balance_sheet": self._fmt_balance_sheet(),
            "market_risk": self._fmt_market_risk(),
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
                self._fmt_profitability(),
                self._fmt_cash_quality(),
                self._fmt_balance_sheet(),
                self._fmt_market_risk(),
            ])


class QualityFactorsModel:
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
        indicators     = indicator_repo.get_latest_indicators(self.stock_symbols, self.signal_day)

        fundamentals   = fundamentals.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        indicators     = indicators.set_index("symbol")

        fundamentals["sector"] = sector_mapping["sector"]
        for col in ("volatility_20", "atr_pct", "drawdown_from_recent_high"):
            fundamentals[col] = indicators[col]

        for col in ["roe", "roic", "operating_margin", "fcf_margin"]:
            fundamentals[f"{col}_percentile"] = fundamentals[col].rank(pct=True) * 100

        fundamentals["quality_composite_percentile"] = (
            fundamentals["roe_percentile"]
            + fundamentals["roic_percentile"]
            + fundamentals["operating_margin_percentile"]
            + fundamentals["fcf_margin_percentile"]
        ) / 4

        self.stock_data = fundamentals

    def _get(self, symbol: str, col: str):
        v = self.stock_data.loc[symbol, col]
        return None if pd.isna(v) else v

    def build_snapshot(self, symbol: str, report_sections: list[str] | str) -> QualitySnapshot:
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        return QualitySnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self._get(symbol, "sector"),
            roe=self._get(symbol, "roe"),
            roa=self._get(symbol, "roa"),
            roic=self._get(symbol, "roic"),
            gross_margin=self._get(symbol, "gross_margin"),
            operating_margin=self._get(symbol, "operating_margin"),
            net_margin=self._get(symbol, "net_margin"),
            fcf_margin=self._get(symbol, "fcf_margin"),
            cash_conversion=self._get(symbol, "cash_conversion"),
            accruals_ratio=self._get(symbol, "accruals_ratio"),
            debt_to_equity=self._get(symbol, "debt_to_equity"),
            net_debt_to_ebitda=self._get(symbol, "net_debt_to_ebitda"),
            interest_coverage=self._get(symbol, "interest_coverage"),
            current_ratio=self._get(symbol, "current_ratio"),
            asset_turnover=self._get(symbol, "asset_turnover"),
            volatility_20=self._get(symbol, "volatility_20"),
            atr_pct=self._get(symbol, "atr_pct"),
            drawdown_from_recent_high=self._get(symbol, "drawdown_from_recent_high"),
            roe_percentile=self._get(symbol, "roe_percentile"),
            roic_percentile=self._get(symbol, "roic_percentile"),
            operating_margin_percentile=self._get(symbol, "operating_margin_percentile"),
            fcf_margin_percentile=self._get(symbol, "fcf_margin_percentile"),
            quality_composite_percentile=self._get(symbol, "quality_composite_percentile"),
            report_sections=report_sections if isinstance(report_sections, list) else [report_sections],
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = QualityFactorsModel(signal_day, symbols)
    report_sections = [
        "profitability",
        "cash_quality",
        "balance_sheet",
        "market_risk",
    ]
    for sym in symbols:
        print(model.build_snapshot(sym, report_sections).to_agent_prompt())
        print()
