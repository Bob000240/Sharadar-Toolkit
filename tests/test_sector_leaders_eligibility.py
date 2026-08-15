from types import SimpleNamespace

import pandas as pd

import research.presets.strat_sector_leaders as sector_leaders


def _assembled_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["PASS", "SMALL", "ADR", "NONUSD"],
            "category": [
                "Domestic Common Stock",
                "Domestic Common Stock",
                "ADR Common Stock",
                "Domestic Common Stock",
            ],
            "currency": ["USD", "USD", "USD", "CAD"],
            "dollar_volume_20d_avg": [6e6, 6e6, 6e6, 6e6],
            "marketcap": [10e9, 9e9, 20e9, 20e9],
            "netinccmnusd": [1.0, 1.0, 1.0, 1.0],
            "return_60d": [0.1, 0.1, 0.1, 0.1],
            "return_252d": [0.2, 0.2, 0.2, 0.2],
            "pct_from_sma_200": [0.05, 0.05, 0.05, 0.05],
            "trend_slope_60d": [0.01, 0.01, 0.01, 0.01],
        }
    )


def test_sector_leader_eligibility_is_owned_by_the_preset():
    result = sector_leaders._ELIGIBILITY_FILTERS.apply(_assembled_frame())

    assert result["ticker"].tolist() == ["PASS"]


def test_screener_builds_eligibility_from_universe_and_attached_signals(monkeypatch):
    frame = _assembled_frame()
    screener = sector_leaders.SLEntryScreener.__new__(
        sector_leaders.SLEntryScreener
    )
    screener.universe = SimpleNamespace(run=lambda signal_day: frame[["ticker"]])

    monkeypatch.setattr(
        sector_leaders,
        "attach_signals",
        lambda universe, signal_day: frame.copy(),
    )
    monkeypatch.setattr(
        sector_leaders.FundamentalSignals,
        "attach_sectors",
        lambda candidates: candidates.assign(sector="Technology"),
    )
    monkeypatch.setattr(
        sector_leaders.FundamentalSignals,
        "attach_sector_ranks",
        lambda candidates, signals, positive_only=(): candidates,
    )
    monkeypatch.setattr(
        sector_leaders.TechnicalSignals,
        "attach_sector_ranks",
        lambda candidates, signals: candidates,
    )
    monkeypatch.setattr(
        sector_leaders.EventSignals,
        "attach_event_facts",
        lambda tickers, signal_day: pd.DataFrame(
            {
                "recent_event_codes": [[] for _ in tickers],
                "days_since_last_earnings": [None for _ in tickers],
            },
            index=pd.Index(tickers, name="ticker"),
        ),
    )

    ranked_tickers = []

    def capture_rank(candidates):
        ranked_tickers.extend(candidates["ticker"])
        return candidates.iloc[0:0]

    monkeypatch.setattr(screener, "rank", capture_rank)

    assert screener.run(pd.Timestamp("2026-08-10")) == []
    assert ranked_tickers == ["PASS"]
