import database.fundamentals_repository as fundamentals_repo
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
class ValueSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Earnings-based
    pe_ratio: float | None
    earnings_yield: float | None

    # Cash flow-based
    price_to_fcf: float | None
    fcf_yield: float | None
    ev_ebitda: float | None
    ev_sales: float | None
    ev_fcf: float | None

    # Asset / revenue-based
    pb_ratio: float | None
    price_to_sales: float | None

    # Yield-based
    dividend_yield: float | None

    # Universe-relative ranks (higher = cheaper)
    earnings_yield_percentile: float
    fcf_yield_percentile: float
    pe_inverted_percentile: float           # low P/E = high percentile
    ev_ebitda_inverted_percentile: float
    ev_sales_inverted_percentile: float
    ps_inverted_percentile: float           # low P/S = high percentile

    # Sector-relative ranks
    pe_sector_percentile: float
    ev_ebitda_sector_percentile: float

    # Composite
    value_composite_percentile: float

    report_sections: list[str]

    def _fmt_header(self) -> str:
        return (
            f"[VALUE] {self.symbol} | {str(self.signal_day)[:10]} | Sector: {self.sector}\n"
            f"Composite rank: {_rank(self.value_composite_percentile)} (higher = cheaper vs peers)"
        )

    def _fmt_earnings_valuation(self) -> str:
        return (
            "Earnings-based:\n"
            f"  P/E: {_x(self.pe_ratio)} (rank {self.pe_inverted_percentile:.0f}th inverted; lower P/E = higher rank) | "
            f"Earnings yield: {_pct(self.earnings_yield)} (rank {self.earnings_yield_percentile:.0f}th)"
        )

    def _fmt_cashflow_valuation(self) -> str:
        return (
            "Cash flow & revenue:\n"
            f"  P/FCF: {_x(self.price_to_fcf)} | "
            f"FCF yield: {_pct(self.fcf_yield)} (rank {self.fcf_yield_percentile:.0f}th) | "
            f"EV/EBITDA: {_x(self.ev_ebitda)} (rank {self.ev_ebitda_inverted_percentile:.0f}th inverted)\n"
            f"  EV/Sales: {_x(self.ev_sales)} (rank {self.ev_sales_inverted_percentile:.0f}th inverted) | "
            f"EV/FCF: {_x(self.ev_fcf)} | "
            f"P/S: {_x(self.price_to_sales)} (rank {self.ps_inverted_percentile:.0f}th inverted)"
        )

    def _fmt_asset_income_valuation(self) -> str:
        return (
            "Asset & income:\n"
            f"  P/B: {_x(self.pb_ratio, '.2f')} | Dividend yield: {_pct(self.dividend_yield)}"
        )

    def _fmt_sector_relative(self) -> str:
        return (
            "Sector-relative (higher = cheaper than sector peers):\n"
            f"  P/E vs sector: {_rank(self.pe_sector_percentile)} | "
            f"EV/EBITDA vs sector: {_rank(self.ev_ebitda_sector_percentile)}"
        )

    def to_agent_prompt(self) -> str:
        prompt_sections = {
            "earnings_valuation": self._fmt_earnings_valuation(),
            "cashflow_valuation": self._fmt_cashflow_valuation(),
            "asset_income_valuation": self._fmt_asset_income_valuation(),
            "sector_relative": self._fmt_sector_relative(),
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
                self._fmt_earnings_valuation(),
                self._fmt_cashflow_valuation(),
                self._fmt_asset_income_valuation(),
                self._fmt_sector_relative(),
            ])


class ValueFactorsModel:
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

        # Universe-wide percentiles (higher = cheaper)
        fundamentals["earnings_yield_percentile"] = fundamentals["earnings_yield"].rank(pct=True) * 100
        fundamentals["fcf_yield_percentile"]      = fundamentals["fcf_yield"].rank(pct=True) * 100

        # Inverted: lower ratio = cheaper = higher percentile
        fundamentals["pe_inverted_percentile"]        = 100 - fundamentals["pe_ratio"].rank(pct=True) * 100
        fundamentals["ev_ebitda_inverted_percentile"] = 100 - fundamentals["ev_ebitda"].rank(pct=True) * 100
        fundamentals["ev_sales_inverted_percentile"]  = 100 - fundamentals["ev_sales"].rank(pct=True) * 100
        fundamentals["ps_inverted_percentile"]        = 100 - fundamentals["price_to_sales"].rank(pct=True) * 100

        fundamentals["value_composite_percentile"] = (
            fundamentals["earnings_yield_percentile"]
            + fundamentals["fcf_yield_percentile"]
            + fundamentals["pe_inverted_percentile"]
            + fundamentals["ev_ebitda_inverted_percentile"]
        ) / 4

        # Sector-relative percentiles (ascending=False → low ratio = high rank)
        fundamentals["pe_sector_percentile"] = (
            fundamentals.groupby("sector")["pe_ratio"]
            .rank(pct=True, ascending=False) * 100
        )
        fundamentals["ev_ebitda_sector_percentile"] = (
            fundamentals.groupby("sector")["ev_ebitda"]
            .rank(pct=True, ascending=False) * 100
        )

        self.stock_data = fundamentals

    def _get(self, symbol: str, col: str):
        v = self.stock_data.loc[symbol, col]
        return None if pd.isna(v) else v

    def build_snapshot(self, symbol: str, report_sections: list[str] | str) -> ValueSnapshot:
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        return ValueSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self._get(symbol, "sector"),
            pe_ratio=self._get(symbol, "pe_ratio"),
            earnings_yield=self._get(symbol, "earnings_yield"),
            price_to_fcf=self._get(symbol, "price_to_fcf"),
            fcf_yield=self._get(symbol, "fcf_yield"),
            ev_ebitda=self._get(symbol, "ev_ebitda"),
            ev_sales=self._get(symbol, "ev_sales"),
            ev_fcf=self._get(symbol, "ev_fcf"),
            pb_ratio=self._get(symbol, "pb_ratio"),
            price_to_sales=self._get(symbol, "price_to_sales"),
            dividend_yield=self._get(symbol, "dividend_yield"),
            earnings_yield_percentile=self._get(symbol, "earnings_yield_percentile"),
            fcf_yield_percentile=self._get(symbol, "fcf_yield_percentile"),
            pe_inverted_percentile=self._get(symbol, "pe_inverted_percentile"),
            ev_ebitda_inverted_percentile=self._get(symbol, "ev_ebitda_inverted_percentile"),
            ev_sales_inverted_percentile=self._get(symbol, "ev_sales_inverted_percentile"),
            ps_inverted_percentile=self._get(symbol, "ps_inverted_percentile"),
            pe_sector_percentile=self._get(symbol, "pe_sector_percentile"),
            ev_ebitda_sector_percentile=self._get(symbol, "ev_ebitda_sector_percentile"),
            value_composite_percentile=self._get(symbol, "value_composite_percentile"),
            report_sections=report_sections if isinstance(report_sections, list) else [report_sections],
        )


if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA", "AVGO", "AMD",
    "ADBE", "CSCO", "ORCL", "CRM", "INTC"]
    signal_day = pd.Timestamp.today()
    model = ValueFactorsModel(signal_day, symbols)
    report_sections = [
        "earnings_valuation",
        "cashflow_valuation",
        "asset_income_valuation",
        "sector_relative",
    ]
    for sym in symbols:
        print(model.build_snapshot(sym, report_sections).to_agent_prompt())
        print()
