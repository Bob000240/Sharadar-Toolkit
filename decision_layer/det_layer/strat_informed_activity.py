"""
Informed-activity Strategy ("smart money"): opportunistic insider buying,
institutional accumulation, and activist (13D) catalysts. Broad universe,
macro-insensitive / contrarian. Episodic by nature, so most names won't qualify.
Signals: sig_insider + sig_institutional + sig_events.
"""

from __future__ import annotations
from datetime import date

import pandas as pd

from data.signals.sig_insider import InsiderModel
from data.signals.sig_institutional import InstitutionalModel
from data.signals.sig_events import EventsModel
from decision_layer.det_layer.strategy import Strategy, ScreenResult

_EXCLUDING_EVENTS = {
    "delisting_risk",
    "bankruptcy",
    "restatement",
    "late_filing",
    "material_impairment",
}


def _institutional_accumulating(inst) -> bool:
    return (
        pd.notna(inst.units_change_pct)
        and inst.units_change_pct > 0
        and inst.holders_change > 0
        and inst.new_holders > inst.closed_positions
    )


class StratInformedActivity(Strategy):
    NAME = "informed_activity"
    PROFILE = {
        "description": "Opportunistic insider buying, institutional accumulation, 13D catalysts.",
        "universe": "US_EQUITY",
        "default_holding_days": 120,
        "max_position_pct": 0.04,
        "max_loss_pct": 0.15,
        "allowed_stop_ids": ["atr_3x", "pct_15"],
        "allowed_target_ids": ["rr_2", "pct_25"],
        "allowed_timeline_ids": ["trend_90d", "trend_120d"],
        "default_stop_id": "atr_3x",
        "default_target_id": "rr_2",
        "default_timeline_id": "trend_120d",
    }

    def screen(self, signal_day: date, tickers: list[str]) -> list[ScreenResult]:
        ts = pd.Timestamp(signal_day)
        prices = self._price_levels(signal_day, tickers)
        if prices.empty:
            return []
        present = prices.index.tolist()

        insiders = InsiderModel(ts, present)
        institutions = InstitutionalModel(ts, present)
        events = EventsModel(ts, present)

        results: list[ScreenResult] = []
        for ticker in present:
            ins = insiders.build_snapshot(ticker)
            inst = institutions.build_snapshot(ticker)
            ev = events.build_snapshot(ticker)

            ev_risks = ev.risk_flags()
            if any(ev_risks.get(code) for code in _EXCLUDING_EVENTS):
                continue
            if ins.risk_flags()["only_selling_30d"]:
                continue

            cluster = ins.cluster_buying()
            officers = ins.officer_activity()
            catalysts = ev.catalyst_flags()

            insider_cluster = cluster["opportunistic_cluster_30d"]
            insider_buy = cluster["opportunistic_buy_30d"]
            accumulating = _institutional_accumulating(inst)
            activist = catalysts["activist_13d_filing"] or catalysts["fresh_13d_code"]

            if not (insider_cluster or accumulating or activist):
                continue

            gates: list[str] = []
            score = 0.0
            if insider_cluster:
                gates.append("opportunistic_insider_cluster")
                score += 0.45
                if officers["opportunistic_senior_cluster"]:
                    gates.append("senior_cluster")
                    score += 0.10
            elif insider_buy:
                gates.append("opportunistic_insider_buy")
                score += 0.25
            if accumulating:
                gates.append("institutional_accumulation")
                score += 0.30
            if activist:
                gates.append("activist_13d")
                score += 0.25

            row = prices.loc[ticker]
            results.append(
                ScreenResult(
                    symbol=ticker,
                    setup_score=min(1.0, score),
                    passed_gates=gates,
                    risk_flags=[k for k, v in ins.risk_flags().items() if v],
                    entry_price=float(row["close"]),
                    atr=float(row["atr_14"]),
                    levels={"sma_50": float(row["sma_50"])},
                    signal_context={
                        "opportunistic_buy_count_30d": ins.opportunistic_buy_count_30d,
                        "unique_opportunistic_buyers_30d": ins.unique_opportunistic_buyers_30d,
                        "opportunistic_buy_value_30d": round(ins.opportunistic_buy_value_30d, 0),
                        "net_buy_ratio_90d": round(ins.net_buy_ratio_90d, 3)
                        if pd.notna(ins.net_buy_ratio_90d) else None,
                        "days_since_last_buy": ins.days_since_last_buy,
                        "institutional_units_change_pct": round(inst.units_change_pct, 4)
                        if pd.notna(inst.units_change_pct) else None,
                        "institutional_holders_change": inst.holders_change,
                        "new_holders": inst.new_holders,
                        "closed_positions": inst.closed_positions,
                        "activist_13d": activist,
                        "days_since_last_activist_13d": ev.days_since_last_activist_13d,
                    },
                )
            )
        return results


if __name__ == "__main__":
    strat = StratInformedActivity()
    packets = strat.run(
        date(2024, 6, 28),
        tickers=["AAPL", "INTC", "PARA", "WBD", "F", "BAC", "OXY", "KMI"],
        persist=False,
    )
    print(f"{strat.NAME}: {len(packets)} candidates")
    for p in packets:
        print(
            f"  {p['symbol']:6s} score={p['setup_score']:.3f} entry={p['entry_price']} "
            f"stop={p['default_stop_id']} target={p['default_target_id']} gates={p['passed_gates']}"
        )
