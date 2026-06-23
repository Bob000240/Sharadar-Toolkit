"""
Drop-in replacement for raw_data/market_data.py (Alpaca).

When switching from Alpaca to Schwab, replace:
    from raw_data.market_data import MarketData
with:
    from schwab.market_data import MarketData

Same class name, same method signatures, same DataFrame column layout.
"""

import pandas as pd
import requests

from schwab.auth import SchwabAuth

_MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"


class MarketData:
    def __init__(self):
        self._auth = SchwabAuth()
        self.ohlcv = pd.DataFrame()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._auth.get_access_token()}"}

    def get_OHLCV(
        self,
        symbols: list[str] | str,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> pd.DataFrame:
        symbols = [symbols] if isinstance(symbols, str) else symbols
        start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_date).timestamp() * 1000)

        data_list = []
        for sym in symbols:
            r = requests.get(
                f"{_MARKET_BASE}/pricehistory",
                params={
                    "symbol": sym,
                    "periodType": "year",
                    "frequencyType": "daily",
                    "frequency": 1,
                    "startDate": start_ms,
                    "endDate": end_ms,
                    "needExtendedHoursData": False,
                },
                headers=self._headers(),
            )
            r.raise_for_status()
            for candle in r.json().get("candles", []):
                data_list.append(
                    {
                        "symbol": sym,
                        "date": pd.Timestamp(candle["datetime"], unit="ms").date(),
                        "open": candle["open"],
                        "high": candle["high"],
                        "low": candle["low"],
                        "close": candle["close"],
                        "volume": candle["volume"],
                    }
                )

        self.ohlcv = pd.DataFrame(data_list)
        if not self.ohlcv.empty:
            self.ohlcv["date"] = pd.to_datetime(self.ohlcv["date"])
        return self.ohlcv

    def get_live_snapshot(self, symbols: list[str] | str) -> pd.DataFrame:
        """
        Fetches the latest quote for each symbol.
        Returns a DataFrame indexed by symbol with columns: open, high, low, close, volume.
        Falls back to empty DataFrame if data is unavailable.
        """
        symbols = [symbols] if isinstance(symbols, str) else symbols
        try:
            r = requests.get(
                f"{_MARKET_BASE}/quotes",
                params={"symbols": ",".join(symbols), "fields": "quote"},
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return pd.DataFrame()

        rows = []
        for sym in symbols:
            q = data.get(sym, {}).get("quote")
            if not q:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "open": float(q.get("openPrice", 0)),
                    "high": float(q.get("highPrice", 0)),
                    "low": float(q.get("lowPrice", 0)),
                    "close": float(q.get("lastPrice", 0)),
                    "volume": float(q.get("totalVolume", 0)),
                }
            )

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("symbol")
