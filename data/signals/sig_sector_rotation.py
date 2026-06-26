import pandas as pd
import numpy as np
from dataclasses import dataclass

import database.market.fund_repo as fund_repo
from set_up.config import ETF_SECTOR_MAP

_ETF_TICKERS = list(ETF_SECTOR_MAP.keys())

# Sector names follow the Sharadar/Zacks taxonomy (must match ETF_SECTOR_MAP values).
_CYCLICAL_SECTORS = {
    "Technology",
    "Consumer Cyclical",
    "Communication Services",
    "Financial Services",
    "Industrials",
    "Energy",
    "Basic Materials",
}
_DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare", "Real Estate"}


@dataclass
class SectorRotationSnapshot:
    ticker: str
    signal_day: pd.Timestamp
    sector: str | None

    # Ticker's sector performance
    sector_return_5d: float | None
    sector_return_20d: float | None
    sector_return_60d: float | None
    sector_rank_20d: int | None  # 1 = best, 11 = worst among all sectors

    # Market-wide context
    top_3_sectors: list[str]
    bottom_3_sectors: list[str]
    cyclicals_leading: bool
    cyclical_vs_defensive_spread: float  # avg cyclical - avg defensive (20d)

    def sector_strength(self) -> dict[str, bool]:
        rank = self.sector_rank_20d
        ret = self.sector_return_20d
        return {
            "sector_top_3": rank is not None and rank <= 3,
            "sector_top_half": rank is not None and rank <= 5,
            "sector_bottom_3": rank is not None and rank >= 9,
            "sector_positive": ret is not None and ret > 0,
            "sector_strong": ret is not None and ret > 0.03,
            "sector_weak": ret is not None and ret < -0.03,
        }

    def market_regime(self) -> dict[str, bool]:
        spread = self.cyclical_vs_defensive_spread
        return {
            "cyclicals_leading": self.cyclicals_leading,
            "defensives_leading": not self.cyclicals_leading,
            "strong_risk_on": spread > 0.03,
            "strong_risk_off": spread < -0.03,
            "in_leading_sector": self.sector_rank_20d is not None
            and self.sector_rank_20d <= 3,
            "in_lagging_sector": self.sector_rank_20d is not None
            and self.sector_rank_20d >= 9,
        }

    def sector_score(self) -> float:
        """0-1: higher = sector is leading."""
        if self.sector_rank_20d is None:
            return 0.5
        return 1.0 - (self.sector_rank_20d - 1) / 10


class SectorRotationModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._sector_data: pd.DataFrame | None = None
        self._top_3: list[str] = []
        self._bottom_3: list[str] = []
        self._cyclicals_leading = False
        self._spread = 0.0
        self.load_data()

    def load_data(self) -> None:
        lookback = self.signal_day - pd.Timedelta(days=90)
        prices = fund_repo.get(
            tickers=_ETF_TICKERS,
            start_date=str(lookback.date()),
            end_date=str(self.signal_day.date()),
        )
        if prices.empty:
            return

        prices["date"] = pd.to_datetime(prices["date"])
        rows = []
        for etf, grp in prices.groupby("ticker"):
            sector = ETF_SECTOR_MAP.get(etf)
            if not sector:
                continue
            c = grp.sort_values("date")["close"].values
            rows.append(
                {
                    "sector": sector,
                    "return_5d": (c[-1] / c[-6] - 1) if len(c) >= 6 else float("nan"),
                    "return_20d": (c[-1] / c[-21] - 1)
                    if len(c) >= 21
                    else float("nan"),
                    "return_60d": (c[-1] / c[-61] - 1)
                    if len(c) >= 61
                    else float("nan"),
                }
            )

        df = pd.DataFrame(rows).set_index("sector")
        df["rank_20d"] = df["return_20d"].rank(ascending=False, method="min")

        sorted_df = df.sort_values("return_20d", ascending=False)
        self._top_3 = sorted_df.index[:3].tolist()
        self._bottom_3 = sorted_df.index[-3:].tolist()

        cyc_ret = df[df.index.isin(_CYCLICAL_SECTORS)]["return_20d"].mean()
        def_ret = df[df.index.isin(_DEFENSIVE_SECTORS)]["return_20d"].mean()
        if pd.notna(cyc_ret) and pd.notna(def_ret):
            self._spread = float(cyc_ret - def_ret)
        self._cyclicals_leading = self._spread > 0
        self._sector_data = df

    def build_snapshot(self, ticker: str, sector: str | None) -> SectorRotationSnapshot:
        df = self._sector_data
        if df is None or sector is None or sector not in df.index:
            return SectorRotationSnapshot(
                ticker=ticker,
                signal_day=self.signal_day,
                sector=sector,
                sector_return_5d=None,
                sector_return_20d=None,
                sector_return_60d=None,
                sector_rank_20d=None,
                top_3_sectors=self._top_3,
                bottom_3_sectors=self._bottom_3,
                cyclicals_leading=self._cyclicals_leading,
                cyclical_vs_defensive_spread=self._spread,
            )
        row = df.loc[sector]
        return SectorRotationSnapshot(
            ticker=ticker,
            signal_day=self.signal_day,
            sector=sector,
            sector_return_5d=float(row["return_5d"])
            if pd.notna(row["return_5d"])
            else None,
            sector_return_20d=float(row["return_20d"])
            if pd.notna(row["return_20d"])
            else None,
            sector_return_60d=float(row["return_60d"])
            if pd.notna(row["return_60d"])
            else None,
            sector_rank_20d=int(row["rank_20d"]) if pd.notna(row["rank_20d"]) else None,
            top_3_sectors=self._top_3,
            bottom_3_sectors=self._bottom_3,
            cyclicals_leading=self._cyclicals_leading,
            cyclical_vs_defensive_spread=self._spread,
        )


def print_snapshot_report(snap: SectorRotationSnapshot) -> None:
    rank = f"{snap.sector_rank_20d}/11" if snap.sector_rank_20d is not None else "n/a"
    r20 = (
        f"{snap.sector_return_20d:.1%}" if snap.sector_return_20d is not None else "n/a"
    )
    r5 = f"{snap.sector_return_5d:.1%}" if snap.sector_return_5d is not None else "n/a"
    print(f"\n=== {snap.ticker} ({snap.sector}) | {snap.signal_day.date()} ===")
    print(f"  Sector 5d/20d: {r5} / {r20}  |  Rank: {rank}")
    print(f"  Top sectors:    {snap.top_3_sectors}")
    print(f"  Bottom sectors: {snap.bottom_3_sectors}")
    print(
        f"  Cyclical/defensive spread: {snap.cyclical_vs_defensive_spread:+.1%}  "
        f"({'cyclicals leading' if snap.cyclicals_leading else 'defensives leading'})"
    )
    print(f"  Sector Score:   {snap.sector_score():.3f}")
    print(f"  Sector Strength: {snap.sector_strength()}")
    print(f"  Market Regime:   {snap.market_regime()}")


if __name__ == "__main__":
    signal_day = pd.Timestamp("2024-06-30")
    model = SectorRotationModel(signal_day=signal_day)
    for ticker, sector in [
        ("AAPL", "Technology"),
        ("JPM", "Financial Services"),
        ("XOM", "Energy"),
    ]:
        print_snapshot_report(model.build_snapshot(ticker, sector))
