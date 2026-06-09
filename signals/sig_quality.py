import database.fundamentals_repository as fundamentals_repo
import database.indicator_repository as indicator_repo
import database.descriptors_repository as sector_repo
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

    report_sections: list[str]

    def _fmt_header(self) -> str:
        return f"[QUALITY] {self.symbol} | {str(self.signal_day)[:10]} | Sector: {self.sector}"

    def _fmt_profitability(self) -> str:
        return (
            "Profitability:\n"
            f"  ROE: {_pct(self.roe)} (rank {self.roe_percentile:.0f}th) | "
            f"ROA: {_pct(self.roa)} | "
            f"ROIC: {_pct(self.roic)} (rank {self.roic_percentile:.0f}th; quality threshold: >15%)\n"
            f"  Gross margin: {_pct(self.gross_margin)} | "
            f"Op. margin: {_pct(self.operating_margin)} (rank {self.operating_margin_percentile:.0f}th) | "
            f"Net margin: {_pct(self.net_margin)}\n"
            f"  FCF margin: {_pct(self.fcf_margin)} (rank {self.fcf_margin_percentile:.0f}th)"
        )

    def _fmt_cash_quality(self) -> str:
        accruals_str = (
            f"{self.accruals_ratio:.3f} (concern: >0.10)"
            if self.accruals_ratio is not None and self.accruals_ratio == self.accruals_ratio
            else "N/A"
        )
        return (
            "Cash quality:\n"
            f"  Cash conversion (FCF/net income): {_x(self.cash_conversion, '.2f')} (>1.0 = earnings backed by cash) | "
            f"Accruals ratio: {accruals_str}"
        )

    def _fmt_balance_sheet(self) -> str:
        ic_str = (
            f"{self.interest_coverage:.1f}x (>3x safe)"
            if self.interest_coverage is not None and self.interest_coverage == self.interest_coverage
            else "N/A (net interest income)"
        )
        nd_str = (
            f"{self.net_debt_to_ebitda:.2f}x (<3x conservative)"
            if self.net_debt_to_ebitda is not None and self.net_debt_to_ebitda == self.net_debt_to_ebitda
            else "N/A"
        )
        return (
            "Balance sheet:\n"
            f"  D/E: {_x(self.debt_to_equity, '.2f')} (<1.0 conservative) | "
            f"Net debt/EBITDA: {nd_str} | "
            f"Interest coverage: {ic_str}\n"
            f"  Current ratio: {_x(self.current_ratio, '.2f')} (>1.0 liquid) | "
            f"Asset turnover: {_x(self.asset_turnover, '.2f')}"
        )

    def _fmt_market_risk(self) -> str:
        drawdown_note = (
            "at recent peak"
            if self.drawdown_from_recent_high == 0
            else f"{self.drawdown_from_recent_high:.1%} off 20d high"
        )
        return (
            "Market risk:\n"
            f"  20d vol (ann.): {self.volatility_20:.1%} | "
            f"ATR: {self.atr_pct:.2%} of price | "
            f"Drawdown: {drawdown_note}"
        )

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
            report_sections=report_sections if isinstance(report_sections, list) else [report_sections],
        )


if __name__ == "__main__":
    symbols = ["AAPL", "MSFT", "NVDA", "AVGO", "AMD",
    "ADBE", "CSCO", "ORCL", "CRM", "INTC"]
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
