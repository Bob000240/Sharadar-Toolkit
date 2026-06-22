import database.macro_repository as macro_repo
import database.indicator_repository as indicator_repo
import pandas as pd
from dataclasses import dataclass


def _classify_regime(
    vix: float,
    spy_above_sma_200: bool,
    yield_curve: float,
    credit_spread_hy: float,
) -> str:
    risk_off_signals = sum([
        vix > 25,
        not spy_above_sma_200,
        yield_curve < 0,
        credit_spread_hy > 5.0,
    ])
    if risk_off_signals == 0:
        return "risk_on"
    elif risk_off_signals >= 3:
        return "risk_off"
    else:
        return "caution"


@dataclass
class MacroSnapshot:
    # Identity
    signal_day: pd.Timestamp

    # Interest rates
    yield_10y: float
    yield_2y: float
    yield_curve: float      # 10y - 2y; positive = normal, negative = inverted
    real_yield: float       # 10y yield - CPI YoY

    # Economic indicators
    cpi_yoy: float
    unemployment_rate: float

    # Risk indicators
    credit_spread_hy: float     # high-yield spread (%)
    credit_spread_ig: float     # investment-grade spread (%)
    vix: float
    spy_above_sma_200: bool

    # Regime
    risk_regime: str    # "risk_on", "caution", "risk_off"


class MacroFactorsModel:
    def __init__(self, signal_day: pd.Timestamp):
        self.signal_day = signal_day
        self._macro = None
        self._spy_above_sma_200 = False
        self._load_data()

    def _load_data(self):
        macro_df = macro_repo.get_latest_macro(self.signal_day)
        spy_df = indicator_repo.get_latest_indicators(["SPY"], self.signal_day)

        if macro_df.empty:
            raise ValueError(f"No macro data found on or before {self.signal_day}")

        self._macro = macro_df.iloc[0]

        if not spy_df.empty:
            spy_row = spy_df[spy_df["symbol"] == "SPY"]
            if not spy_row.empty:
                r = spy_row.iloc[0]
                self._spy_above_sma_200 = bool(r["close"] > r["sma_200"]) if r["sma_200"] else False

    def build_snapshot(self) -> MacroSnapshot:
        m = self._macro
        return MacroSnapshot(
            signal_day=self.signal_day,
            yield_10y=m["yield_10y"],
            yield_2y=m["yield_2y"],
            yield_curve=m["yield_curve"],
            real_yield=m["real_yield"],
            cpi_yoy=m["cpi_yoy"],
            unemployment_rate=m["unemployment_rate"],
            credit_spread_hy=m["credit_spread_hy"],
            credit_spread_ig=m["credit_spread_ig"],
            vix=m["vix"],
            spy_above_sma_200=self._spy_above_sma_200,
            risk_regime=_classify_regime(
                m["vix"],
                self._spy_above_sma_200,
                m["yield_curve"],
                m["credit_spread_hy"],
            ),
        )


if __name__ == "__main__":
    signal_day = pd.Timestamp.today()
    model = MacroFactorsModel(signal_day)
    print(model.build_snapshot())
