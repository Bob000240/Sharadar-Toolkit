import database.indicator_repository as indicator_repo
import pandas as pd
from dataclasses import dataclass

SECTOR_ETF_MAP = {
    "XLK":  "Technology",
    "XLV":  "Healthcare",
    "XLF":  "Financial Services",
    "XLY":  "Consumer Cyclical",
    "XLP":  "Consumer Defensive",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLI":  "Industrials",
    "XLB":  "Basic Materials",
    "XLRE": "Real Estate",
    "XLC":  "Communication Services",
}

CYCLICAL_SECTORS  = {"Technology", "Consumer Cyclical", "Communication Services",
                     "Financial Services", "Industrials", "Energy"}
DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare",
                     "Real Estate", "Basic Materials"}


@dataclass
class SectorRotationSnapshot:
    # Identity
    signal_day: pd.Timestamp

    # Per-sector returns  {sector_name: return}
    sector_returns_5d:  dict
    sector_returns_20d: dict
    sector_returns_60d: dict

    # Excess return vs SPY  {sector_name: excess_return}
    sector_vs_spy_5d:  dict
    sector_vs_spy_20d: dict

    # Rankings  {sector_name: rank}  1 = best 20d performer
    sector_rank_20d: dict

    # Summary
    top_3_sectors:    list
    bottom_3_sectors: list

    # Rotation regime
    cyclical_avg_return_20d:      float
    defensive_avg_return_20d:     float
    cyclical_vs_defensive_spread: float
    rotation_regime: str    # "cyclical", "defensive", "neutral"

    # Breadth
    pct_sectors_above_spy_20d: float
    n_sectors_positive_20d:    int

class SectorRotationFactorsModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._etf_data = None
        self._spy_returns: dict = {}
        self._load_data()

    def _load_data(self):
        etf_symbols = list(SECTOR_ETF_MAP.keys())
        all_symbols = etf_symbols + ["SPY"]

        indicators = indicator_repo.get_latest_indicators(all_symbols, self.signal_day)
        indicators = indicators.set_index("symbol")

        spy = indicators.loc["SPY"]
        self._spy_returns = {
            "5d":  spy["return_5d"],
            "20d": spy["return_20d"],
            "60d": spy["return_60d"],
        }

        etf_data = indicators.loc[etf_symbols].copy()
        etf_data["sector"] = etf_data.index.map(SECTOR_ETF_MAP)
        etf_data["sector_vs_spy_5d"]  = etf_data["return_5d"]  - spy["return_5d"]
        etf_data["sector_vs_spy_20d"] = etf_data["return_20d"] - spy["return_20d"]
        etf_data["rank_20d"] = (
            etf_data["return_20d"].rank(ascending=False).astype(int)
        )
        self._etf_data = etf_data

    def build_snapshot(self) -> SectorRotationSnapshot:
        d = self._etf_data

        sector_returns_5d  = dict(zip(d["sector"], d["return_5d"]))
        sector_returns_20d = dict(zip(d["sector"], d["return_20d"]))
        sector_returns_60d = dict(zip(d["sector"], d["return_60d"]))
        sector_vs_spy_5d   = dict(zip(d["sector"], d["sector_vs_spy_5d"]))
        sector_vs_spy_20d  = dict(zip(d["sector"], d["sector_vs_spy_20d"]))
        sector_rank_20d    = dict(zip(d["sector"], d["rank_20d"]))

        sorted_sectors  = sorted(sector_rank_20d, key=lambda s: sector_rank_20d[s])
        top_3    = sorted_sectors[:3]
        bottom_3 = sorted_sectors[-3:]

        cyc_returns = [sector_returns_20d[s] for s in sector_returns_20d if s in CYCLICAL_SECTORS]
        def_returns = [sector_returns_20d[s] for s in sector_returns_20d if s in DEFENSIVE_SECTORS]
        cyc_avg = sum(cyc_returns) / len(cyc_returns)
        def_avg = sum(def_returns) / len(def_returns)
        spread  = cyc_avg - def_avg

        regime = "cyclical" if spread > 0.01 else ("defensive" if spread < -0.01 else "neutral")

        pct_above_spy = (
            sum(1 for v in sector_vs_spy_20d.values() if v > 0) / len(sector_vs_spy_20d)
        )
        n_positive = sum(1 for v in sector_returns_20d.values() if v > 0)

        return SectorRotationSnapshot(
            signal_day=self.signal_day,
            sector_returns_5d=sector_returns_5d,
            sector_returns_20d=sector_returns_20d,
            sector_returns_60d=sector_returns_60d,
            sector_vs_spy_5d=sector_vs_spy_5d,
            sector_vs_spy_20d=sector_vs_spy_20d,
            sector_rank_20d=sector_rank_20d,
            top_3_sectors=top_3,
            bottom_3_sectors=bottom_3,
            cyclical_avg_return_20d=cyc_avg,
            defensive_avg_return_20d=def_avg,
            cyclical_vs_defensive_spread=spread,
            rotation_regime=regime,
            pct_sectors_above_spy_20d=pct_above_spy,
            n_sectors_positive_20d=n_positive,
        )


if __name__ == "__main__":
    signal_day = pd.Timestamp.today()
    model = SectorRotationFactorsModel(signal_day)
    print(model.build_snapshot())
