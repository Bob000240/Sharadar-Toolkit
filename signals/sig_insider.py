import database.insider_repository as insider_repo
import database.sector_data_repository as sector_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class InsiderTransactionSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    sector: str

    # Transaction volume (trailing 90 days)
    buys_90d:  int
    sells_90d: int

    # Transaction value (trailing 90 days, USD)
    buy_value_90d:  float
    sell_value_90d: float
    net_value_90d:  float       # positive = net buying
    buy_sell_ratio: float       # <1 = more selling; >1 = more buying

    # Officer-level signals
    ceo_buying:       bool
    cfo_buying:       bool
    cluster_buy_flag: bool      # 3+ distinct insiders buying within 30 days

    @staticmethod
    def _usd(v: float) -> str:
        if abs(v) >= 1e6:
            return f"${v/1e6:+.1f}M"
        return f"${v/1e3:+.0f}K"

    def _fmt_header(self) -> str:
        net_note = "net buying" if self.net_value_90d > 0 else "net selling"
        return "\n".join([
            f"INSIDER TRANSACTION ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Sector: {self.sector}",
            f"Summary: {net_note} over trailing 90 days  (net value: {self._usd(self.net_value_90d)})",
        ])

    def _fmt_transaction_summary(self) -> str:
        ratio_note = (
            "above 1.0 — more buying than selling"
            if self.buy_sell_ratio >= 1.0
            else "below 1.0 — more selling than buying"
        )
        return "\n".join([
            "--- TRANSACTION SUMMARY (TRAILING 90 DAYS) ---",
            f"  Open-market buys:    {self.buys_90d:>4} transactions   (value: {self._usd(self.buy_value_90d)})",
            f"  Open-market sells:   {self.sells_90d:>4} transactions   (value: {self._usd(self.sell_value_90d)})",
            f"  Net insider value:   {self._usd(self.net_value_90d)}",
            f"  Buy/sell ratio:      {self.buy_sell_ratio:.2f}  ({ratio_note})",
        ])

    def _fmt_officer_activity(self) -> str:
        cluster_note = (
            "YES — strong conviction signal (3+ insiders buying within 30 days)"
            if self.cluster_buy_flag
            else "No"
        )
        return "\n".join([
            "--- OFFICER ACTIVITY ---",
            f"  CEO buying:           {self.ceo_buying}  (highest-conviction insider signal)",
            f"  CFO buying:           {self.cfo_buying}  (financial visibility signal)",
            f"  Cluster buy flag:     {cluster_note}",
        ])

    def to_agent_prompt(self) -> str:
        return "\n\n".join([
            self._fmt_header(),
            self._fmt_transaction_summary(),
            self._fmt_officer_activity(),
        ])


class InsiderFactorsModel:
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
        insider = insider_repo.get_latest_insider(self.stock_symbols, self.signal_day)
        sector_mapping = sector_repo.get_sector_mapping(self.stock_symbols)

        insider = insider.set_index("symbol")
        sector_mapping = sector_mapping.set_index("symbol")
        insider["sector"] = sector_mapping["sector"]

        self.stock_data = insider

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> InsiderTransactionSnapshot:
        return InsiderTransactionSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            sector=self.get(symbol, "sector"),
            buys_90d=int(self.get(symbol, "buys_90d")),
            sells_90d=int(self.get(symbol, "sells_90d")),
            buy_value_90d=self.get(symbol, "buy_value_90d"),
            sell_value_90d=self.get(symbol, "sell_value_90d"),
            net_value_90d=self.get(symbol, "net_value_90d"),
            buy_sell_ratio=self.get(symbol, "buy_sell_ratio"),
            ceo_buying=bool(self.get(symbol, "ceo_buying")),
            cfo_buying=bool(self.get(symbol, "cfo_buying")),
            cluster_buy_flag=bool(self.get(symbol, "cluster_buy_flag")),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = InsiderFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
