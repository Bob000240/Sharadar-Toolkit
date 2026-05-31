import database.fundamentals_repository as fundamentals_repo
import database.sector_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class ValueSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Earnings-based
    pe_ratio: float
    forward_pe: float
    peg_ratio: float
    earnings_yield: float

    # Cash flow-based
    price_to_fcf: float
    fcf_yield: float
    ev_ebitda: float

    # Asset & income
    pb_ratio: float
    dividend_yield: float
    buyback_yield: float

    # Universe-relative ranks (higher = cheaper vs universe peers)
    earnings_yield_percentile: float        # normal rank; high yield = cheap
    fcf_yield_percentile: float             # normal rank
    pe_inverted_percentile: float           # inverted; low P/E = high percentile
    ev_ebitda_inverted_percentile: float    # inverted

    # Sector-relative ranks (higher = cheaper vs sector peers)
    pe_sector_percentile: float
    ev_ebitda_sector_percentile: float

    # Composite
    value_composite_percentile: float

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    @staticmethod
    def _rank(v: float) -> str:
        return f"{v:.0f}th percentile"

    def _fmt_header(self) -> str:
        return "\n".join([
            f"VALUE ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Value composite rank: {self._rank(self.value_composite_percentile)}  (higher = cheaper vs universe peers)",
        ])

    def _fmt_earnings_valuation(self) -> str:
        return "\n".join([
            "--- EARNINGS-BASED VALUATION ---",
            f"  P/E ratio:       {self.pe_ratio:.1f}x   (universe rank: {self._rank(self.pe_inverted_percentile)}; lower P/E = higher rank)",
            f"  Forward P/E:     {self.forward_pe:.1f}x",
            f"  PEG ratio:       {self.peg_ratio:.2f}   (<1.0 = growing faster than valuation implies)",
            f"  Earnings yield:  {self._pct(self.earnings_yield)}   (universe rank: {self._rank(self.earnings_yield_percentile)})",
        ])

    def _fmt_cashflow_valuation(self) -> str:
        return "\n".join([
            "--- CASH FLOW VALUATION ---",
            f"  Price-to-FCF:    {self.price_to_fcf:.1f}x   (universe rank: {self._rank(self.ev_ebitda_inverted_percentile)})",
            f"  FCF yield:       {self._pct(self.fcf_yield)}   (universe rank: {self._rank(self.fcf_yield_percentile)})",
            f"  EV/EBITDA:       {self.ev_ebitda:.1f}x",
        ])

    def _fmt_asset_income_valuation(self) -> str:
        return "\n".join([
            "--- ASSET & INCOME VALUATION ---",
            f"  Price-to-book (P/B):       {self.pb_ratio:.2f}x",
            f"  Dividend yield:            {self._pct(self.dividend_yield)}",
            f"  Buyback yield:             {self._pct(self.buyback_yield)}",
            f"  Total shareholder yield:   {self._pct(self.dividend_yield + self.buyback_yield)}",
        ])

    def _fmt_sector_relative(self) -> str:
        return "\n".join([
            "--- SECTOR-RELATIVE VALUATION ---",
            f"  P/E vs sector peers:       {self._rank(self.pe_sector_percentile)}  (higher = cheaper than sector peers)",
            f"  EV/EBITDA vs sector peers: {self._rank(self.ev_ebitda_sector_percentile)}",
        ])

    def to_agent_prompt(self) -> str:
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

        fundamentals = fundamentals.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        fundamentals["sector"] = sector_mapping["sector"]

        # Universe-wide percentiles (higher = cheaper)
        fundamentals["earnings_yield_percentile"] = (
            fundamentals["earnings_yield"].rank(pct=True) * 100
        )
        fundamentals["fcf_yield_percentile"] = (
            fundamentals["fcf_yield"].rank(pct=True) * 100
        )
        # Inverted: lower ratio = cheaper = higher percentile
        fundamentals["pe_inverted_percentile"] = (
            100 - fundamentals["pe_ratio"].rank(pct=True) * 100
        )
        fundamentals["ev_ebitda_inverted_percentile"] = (
            100 - fundamentals["ev_ebitda"].rank(pct=True) * 100
        )

        fundamentals["value_composite_percentile"] = (
            fundamentals["earnings_yield_percentile"]
            + fundamentals["fcf_yield_percentile"]
            + fundamentals["pe_inverted_percentile"]
            + fundamentals["ev_ebitda_inverted_percentile"]
        ) / 4

        # Sector-relative percentiles
        fundamentals["pe_sector_percentile"] = (
            fundamentals.groupby("sector")["pe_ratio"]
            .rank(pct=True, ascending=False) * 100
        )
        fundamentals["ev_ebitda_sector_percentile"] = (
            fundamentals.groupby("sector")["ev_ebitda"]
            .rank(pct=True, ascending=False) * 100
        )

        self.stock_data = fundamentals

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> ValueSnapshot:
        return ValueSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self.get(symbol, "sector"),
            pe_ratio=self.get(symbol, "pe_ratio"),
            forward_pe=self.get(symbol, "forward_pe"),
            peg_ratio=self.get(symbol, "peg_ratio"),
            earnings_yield=self.get(symbol, "earnings_yield"),
            price_to_fcf=self.get(symbol, "price_to_fcf"),
            fcf_yield=self.get(symbol, "fcf_yield"),
            ev_ebitda=self.get(symbol, "ev_ebitda"),
            pb_ratio=self.get(symbol, "pb_ratio"),
            dividend_yield=self.get(symbol, "dividend_yield"),
            buyback_yield=self.get(symbol, "buyback_yield"),
            earnings_yield_percentile=self.get(symbol, "earnings_yield_percentile"),
            fcf_yield_percentile=self.get(symbol, "fcf_yield_percentile"),
            pe_inverted_percentile=self.get(symbol, "pe_inverted_percentile"),
            ev_ebitda_inverted_percentile=self.get(symbol, "ev_ebitda_inverted_percentile"),
            pe_sector_percentile=self.get(symbol, "pe_sector_percentile"),
            ev_ebitda_sector_percentile=self.get(symbol, "ev_ebitda_sector_percentile"),
            value_composite_percentile=self.get(symbol, "value_composite_percentile"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = ValueFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
