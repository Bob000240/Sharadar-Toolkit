"""
Drop-in replacement for:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

When switching from Alpaca to Schwab, update pm_agent.py imports to:
    from schwab.client import TradingClient, MarketOrderRequest, OrderSide, TimeInForce
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests

from schwab.auth import SchwabAuth

_TRADER_BASE = "https://api.schwabapi.com/trader/v1"


# ------------------------------------------------------------------
# Enums and request types — same names as Alpaca's
# ------------------------------------------------------------------

class OrderSide(Enum):
    BUY  = "BUY"
    SELL = "SELL"


class TimeInForce(Enum):
    DAY = "DAY"
    GTC = "GOOD_TILL_CANCEL"


@dataclass
class MarketOrderRequest:
    symbol:        str
    qty:           int
    side:          OrderSide
    time_in_force: TimeInForce


# ------------------------------------------------------------------
# Response objects — mirror Alpaca attribute names so pm_agent.py
# needs zero changes when you swap the client
# ------------------------------------------------------------------

@dataclass
class _Position:
    symbol:           str
    qty:              str   # str so float(p.qty) keeps working
    market_value:     str
    avg_entry_price:  str
    current_price:    str
    unrealized_pl:    str
    unrealized_plpc:  str


@dataclass
class _Account:
    portfolio_value: str
    cash:            str


@dataclass
class _OrderResponse:
    id: str


# ------------------------------------------------------------------
# TradingClient — same name as Alpaca's
# ------------------------------------------------------------------

class TradingClient:
    def __init__(self):
        self._auth = SchwabAuth()
        self._account_hash: Optional[str] = None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._auth.get_access_token()}"}

    def _get_account_hash(self) -> str:
        if self._account_hash:
            return self._account_hash
        r = requests.get(f"{_TRADER_BASE}/accounts/accountNumbers", headers=self._headers())
        r.raise_for_status()
        accounts = r.json()
        if not accounts:
            raise RuntimeError("No Schwab accounts found.")
        self._account_hash = accounts[0]["hashValue"]
        return self._account_hash

    # ------------------------------------------------------------------
    # Mirror of alpaca.trading.client.TradingClient methods
    # ------------------------------------------------------------------

    def get_all_positions(self) -> list[_Position]:
        hash_ = self._get_account_hash()
        r = requests.get(
            f"{_TRADER_BASE}/accounts/{hash_}",
            params={"fields": "positions"},
            headers=self._headers(),
        )
        r.raise_for_status()
        raw_positions = r.json().get("securitiesAccount", {}).get("positions", [])

        positions = []
        for p in raw_positions:
            symbol      = p["instrument"]["symbol"]
            qty         = float(p.get("longQuantity", 0)) - float(p.get("shortQuantity", 0))
            avg_price   = float(p.get("averagePrice", 0))
            mkt_value   = float(p.get("marketValue", 0))
            open_pl     = float(p.get("longOpenProfitLoss", 0))
            current_price = (mkt_value / qty) if qty else avg_price
            open_pl_pct = (open_pl / (avg_price * qty)) if avg_price and qty else 0.0

            positions.append(_Position(
                symbol          = symbol,
                qty             = str(qty),
                market_value    = str(mkt_value),
                avg_entry_price = str(avg_price),
                current_price   = str(current_price),
                unrealized_pl   = str(open_pl),
                unrealized_plpc = str(open_pl_pct),
            ))
        return positions

    def get_account(self) -> _Account:
        hash_ = self._get_account_hash()
        r = requests.get(f"{_TRADER_BASE}/accounts/{hash_}", headers=self._headers())
        r.raise_for_status()
        balances = r.json().get("securitiesAccount", {}).get("currentBalances", {})
        return _Account(
            portfolio_value = str(balances.get("liquidationValue", 0)),
            cash            = str(balances.get("cashBalance", 0)),
        )

    def submit_order(self, req: MarketOrderRequest) -> _OrderResponse:
        hash_ = self._get_account_hash()
        payload = {
            "orderType":          "MARKET",
            "session":            "NORMAL",
            "duration":           req.time_in_force.value,
            "orderStrategyType":  "SINGLE",
            "orderLegCollection": [
                {
                    "instruction": req.side.value,
                    "quantity":    req.qty,
                    "instrument":  {
                        "symbol":    req.symbol,
                        "assetType": "EQUITY",
                    },
                }
            ],
        }
        r = requests.post(
            f"{_TRADER_BASE}/accounts/{hash_}/orders",
            json=payload,
            headers=self._headers(),
        )
        r.raise_for_status()
        # Schwab returns 201 with the order ID in the Location header, not the body
        location = r.headers.get("Location", "")
        order_id = location.rstrip("/").split("/")[-1] if location else "unknown"
        return _OrderResponse(id=order_id)
