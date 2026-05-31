import database.fundamentals_repository as fundamentals_repo
import database.indicator_repository as indicator_repo
import database.sector_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class QualitySnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Profitability
    roe: float
    roic: float
    gross_margin: float
    operating_margin: float
    fcf_margin: float

    # Cash quality
    cash_conversion: float
    accruals_ratio: float

    # Balance sheet
    debt_to_equity: float
    interest_coverage: float

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

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    @staticmethod
    def _rank(v: float) -> str:
        return f"{v:.0f}th percentile"

    def _fmt_header(self) -> str:
        return "\n".join([
            f"QUALITY ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Quality composite rank: {self._rank(self.quality_composite_percentile)}  (avg of ROE, ROIC, operating margin, FCF margin percentiles)",
        ])

    def _fmt_profitability(self) -> str:
        return "\n".join([
            "--- PROFITABILITY ---",
            f"  Return on equity (ROE):              {self._pct(self.roe)}   (universe rank: {self._rank(self.roe_percentile)})",
            f"  Return on invested capital (ROIC):   {self._pct(self.roic)}   (universe rank: {self._rank(self.roic_percentile)})",
            f"  Gross margin:                        {self._pct(self.gross_margin)}",
            f"  Operating margin:                    {self._pct(self.operating_margin)}   (universe rank: {self._rank(self.operating_margin_percentile)})",
            f"  Free cash flow margin:               {self._pct(self.fcf_margin)}   (universe rank: {self._rank(self.fcf_margin_percentile)})",
        ])

    def _fmt_cash_quality(self) -> str:
        return "\n".join([
            "--- CASH QUALITY ---",
            f"  Cash conversion (FCF / net income):  {self.cash_conversion:.2f}  (>1.0 = earnings fully backed by cash)",
            f"  Accruals ratio:                      {self.accruals_ratio:.3f}  (lower = higher earnings quality; >0.1 = elevated concern)",
        ])

    def _fmt_balance_sheet(self) -> str:
        return "\n".join([
            "--- BALANCE SHEET STRENGTH ---",
            f"  Debt-to-equity:                {self.debt_to_equity:.2f}x  (<1.0 = conservative leverage)",
            f"  Interest coverage (EBIT/Int):  {self.interest_coverage:.1f}x  (>3x = debt burden manageable)",
        ])

    def _fmt_market_risk(self) -> str:
        drawdown_note = "at recent peak" if self.drawdown_from_recent_high == 0 else f"{self.drawdown_from_recent_high:.1%} off 20-day high"
        return "\n".join([
            "--- MARKET RISK ---",
            f"  20-day realised volatility (ann.):  {self.volatility_20:.1%}",
            f"  ATR as % of price:                  {self.atr_pct:.2%}",
            f"  Drawdown from 20-day high:          {drawdown_note}",
        ])

    def to_agent_prompt(self) -> str:
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
        indicators = indicator_repo.get_latest_indicators(self.stock_symbols, self.signal_day)

        fundamentals = fundamentals.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        indicators = indicators.set_index("symbol")

        fundamentals["sector"] = sector_mapping["sector"]
        for col in ("volatility_20", "atr_pct", "drawdown_from_recent_high"):
            fundamentals[col] = indicators[col]

        for col in ["roe", "roic", "operating_margin", "fcf_margin"]:
            fundamentals[f"{col}_percentile"] = (
                fundamentals[col].rank(pct=True) * 100
            )

        fundamentals["quality_composite_percentile"] = (
            fundamentals["roe_percentile"]
            + fundamentals["roic_percentile"]
            + fundamentals["operating_margin_percentile"]
            + fundamentals["fcf_margin_percentile"]
        ) / 4

        self.stock_data = fundamentals

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> QualitySnapshot:
        return QualitySnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self.get(symbol, "sector"),
            roe=self.get(symbol, "roe"),
            roic=self.get(symbol, "roic"),
            gross_margin=self.get(symbol, "gross_margin"),
            operating_margin=self.get(symbol, "operating_margin"),
            fcf_margin=self.get(symbol, "fcf_margin"),
            cash_conversion=self.get(symbol, "cash_conversion"),
            accruals_ratio=self.get(symbol, "accruals_ratio"),
            debt_to_equity=self.get(symbol, "debt_to_equity"),
            interest_coverage=self.get(symbol, "interest_coverage"),
            volatility_20=self.get(symbol, "volatility_20"),
            atr_pct=self.get(symbol, "atr_pct"),
            drawdown_from_recent_high=self.get(symbol, "drawdown_from_recent_high"),
            roe_percentile=self.get(symbol, "roe_percentile"),
            roic_percentile=self.get(symbol, "roic_percentile"),
            operating_margin_percentile=self.get(symbol, "operating_margin_percentile"),
            fcf_margin_percentile=self.get(symbol, "fcf_margin_percentile"),
            quality_composite_percentile=self.get(symbol, "quality_composite_percentile"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = QualityFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
