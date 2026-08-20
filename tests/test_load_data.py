import pandas as pd
import pytest

import pipeline.load_data as load_data


def test_v3_holdings_are_rescaled_to_whole_shares_and_dollars():
    """v3 serves thousands and millions; left raw, the implied price is off
    by three orders of magnitude with nothing to reveal it."""
    chunk = pd.DataFrame(
        [{"ticker": "AAPL", "shrunits": 9483686.0, "shrvalue": 2395886.8}]
    )

    rescaled = load_data._rescale_holdings(chunk)

    assert rescaled.loc[0, "shrunits"] == pytest.approx(9.483686e9)
    assert rescaled.loc[0, "shrvalue"] == pytest.approx(2.3958868e12)
    implied_price = rescaled.loc[0, "shrvalue"] / rescaled.loc[0, "shrunits"]
    assert implied_price == pytest.approx(252.63, abs=0.01)


def test_rescaling_applies_to_the_holdings_tables_alone():
    assert set(load_data._TRANSFORMS) == {"SF3A"}


def test_ticker_export_keeps_equities_and_funds_only():
    rows = pd.DataFrame(
        [
            {"ticker": "AAPL", "table_code": "SEP"},
            {"ticker": "SPY", "table_code": "SFP"},
            {"ticker": "AAPL", "table_code": "SF1"},
        ]
    )

    kept = load_data._ROW_FILTERS["TICKERS"](rows)

    assert kept["table_code"].tolist() == ["SEP", "SFP"]
