"""
Tests for MarketData.get_live_snapshot()   data/live_equity.py

Run with:  python -m pytest tests/test_live_snapshot.py -v
"""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from data.live_equity import MarketData



def _make_bar(open_: float, high: float, low: float, close: float, volume: float) -> MagicMock:
    bar = MagicMock()
    bar.open   = open_
    bar.high   = high
    bar.low    = low
    bar.close  = close
    bar.volume = volume
    return bar


@pytest.fixture
def md():
    with patch("data.live_equity.StockHistoricalDataClient"):
        return MarketData()



class TestGetLiveSnapshotData:

    def test_open_is_first_bar(self, md):
        bars = [
            _make_bar(100.0, 102.0, 99.0, 101.0, 500_000),
            _make_bar(101.0, 105.0, 100.0, 104.0, 300_000),
            _make_bar(104.0, 106.0, 103.0, 105.0, 200_000),
        ]
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": bars}
        result = md.get_live_snapshot(["AAPL"])
        assert np.isclose(result.loc["AAPL", "open"], 100.0)

    def test_high_is_session_max(self, md):
        bars = [
            _make_bar(100.0, 102.0, 99.0, 101.0, 500_000),
            _make_bar(101.0, 108.0, 100.0, 104.0, 300_000),
            _make_bar(104.0, 106.0, 103.0, 105.0, 200_000),
        ]
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": bars}
        result = md.get_live_snapshot(["AAPL"])
        assert np.isclose(result.loc["AAPL", "high"], 108.0)

    def test_low_is_session_min(self, md):
        bars = [
            _make_bar(100.0, 102.0, 97.0, 101.0, 500_000),
            _make_bar(101.0, 105.0, 100.0, 104.0, 300_000),
            _make_bar(104.0, 106.0, 103.0, 105.0, 200_000),
        ]
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": bars}
        result = md.get_live_snapshot(["AAPL"])
        assert np.isclose(result.loc["AAPL", "low"], 97.0)

    def test_close_is_last_bar(self, md):
        bars = [
            _make_bar(100.0, 102.0, 99.0, 101.0, 500_000),
            _make_bar(101.0, 105.0, 100.0, 104.0, 300_000),
            _make_bar(104.0, 106.0, 103.0, 105.0, 200_000),
        ]
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": bars}
        result = md.get_live_snapshot(["AAPL"])
        assert np.isclose(result.loc["AAPL", "close"], 105.0)

    def test_volume_is_session_sum(self, md):
        bars = [
            _make_bar(100.0, 102.0, 99.0, 101.0, 500_000),
            _make_bar(101.0, 105.0, 100.0, 104.0, 300_000),
            _make_bar(104.0, 106.0, 103.0, 105.0, 200_000),
        ]
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": bars}
        result = md.get_live_snapshot(["AAPL"])
        assert np.isclose(result.loc["AAPL", "volume"], 1_000_000.0)

    def test_multiple_symbols_all_returned(self, md):
        md.MarketDataClient.get_stock_bars.return_value.data = {
            "AAPL": [_make_bar(150.0, 155.0, 149.0, 153.0, 1_000_000),
                     _make_bar(153.0, 156.0, 152.0, 154.0, 500_000)],
            "MSFT": [_make_bar(300.0, 305.0, 298.0, 302.0, 800_000)],
        }
        result = md.get_live_snapshot(["AAPL", "MSFT"])
        assert set(result.index) == {"AAPL", "MSFT"}
        assert np.isclose(result.loc["AAPL", "close"], 154.0)
        assert np.isclose(result.loc["AAPL", "volume"], 1_500_000.0)
        assert np.isclose(result.loc["MSFT", "open"], 300.0)



class TestGetLiveSnapshotFallback:

    def test_raises_on_api_exception(self, md):
        md.MarketDataClient.get_stock_bars.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError):
            md.get_live_snapshot(["AAPL"])

    def test_returns_empty_when_no_bars_returned(self, md):
        md.MarketDataClient.get_stock_bars.return_value.data = {"AAPL": []}
        assert md.get_live_snapshot(["AAPL"]).empty

    def test_returns_empty_when_symbol_missing_from_response(self, md):
        md.MarketDataClient.get_stock_bars.return_value.data = {}
        assert md.get_live_snapshot(["AAPL"]).empty



class TestGetLiveSnapshotSymbolMapping:

    def test_hyphen_mapped_to_dot_for_alpaca(self, md):
        md.MarketDataClient.get_stock_bars.return_value.data = {
            "BRK.B": [_make_bar(350.0, 352.0, 349.0, 351.0, 400_000)]
        }
        result = md.get_live_snapshot(["BRK-B"])
        assert "BRK-B" in result.index
        assert np.isclose(result.loc["BRK-B", "close"], 351.0)
