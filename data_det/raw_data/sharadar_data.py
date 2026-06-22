import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_BASE = "https://data.nasdaq.com/api/v3/datatables/SHARADAR"
_PER_PAGE = 10_000


class SharadarData:
    def __init__(self):
        key = os.getenv("SHARADAR_KEY")
        if not key:
            raise ValueError("SHARADAR_KEY not set")
        self._key = key
        self._session = requests.Session()

    def _get(self, table: str, **params) -> pd.DataFrame:
        params = {k: v for k, v in params.items() if v is not None}
        params["api_key"] = self._key
        params["qopts.per_page"] = _PER_PAGE

        rows, cols, cursor = [], None, None
        while True:
            if cursor:
                params["qopts.cursor_id"] = cursor
            r = self._session.get(f"{_BASE}/{table}", params=params, timeout=60)
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                raise RuntimeError(f"Sharadar/{table} error: {body['errors']}")
            dt = body["datatable"]
            if cols is None:
                cols = [c["name"] for c in dt["columns"]]
            rows.extend(dt["data"])
            cursor = body.get("meta", {}).get("next_cursor_id")
            if not cursor:
                break

        return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols or [])

    def _tickers_str(self, tickers: str | list[str] | None) -> str | None:
        if tickers is None:
            return None
        return tickers if isinstance(tickers, str) else ",".join(tickers)

    # -------------------------------------------------------------------------
    # SF1 — Core fundamentals (point-in-time safe via datekey)
    # dimension: ARY=annual, ARQ=quarterly, ART=TTM
    #            MRY/MRQ/MRT = most-recent snapshots (not point-in-time safe)
    # -------------------------------------------------------------------------

    def fundamentals(
        self,
        tickers: str | list[str] | None = None,
        dimension: str = "ARY",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SF1",
            ticker=self._tickers_str(tickers),
            dimension=dimension,
            **{"datekey.gte": start_date, "datekey.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SF2 — Insider transactions (Form 4)
    # -------------------------------------------------------------------------

    def insider_transactions(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SF2",
            ticker=self._tickers_str(tickers),
            **{"filingdate.gte": start_date, "filingdate.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SF3 — Institutional holdings by ticker
    # -------------------------------------------------------------------------

    def institutional_holdings(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SF3",
            ticker=self._tickers_str(tickers),
            **{"calendardate.gte": start_date, "calendardate.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SF3A — Institutional ownership summary (shareholders, call/put holders)
    # -------------------------------------------------------------------------

    def institutional_by_company(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SF3A",
            ticker=self._tickers_str(tickers),
            **{"calendardate.gte": start_date, "calendardate.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SF3B — Institutional holdings by investor
    # -------------------------------------------------------------------------

    def institutional_by_investor(
        self,
        investorname: str | None = None,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SF3B",
            investorname=investorname,
            ticker=self._tickers_str(tickers),
            **{"calendardate.gte": start_date, "calendardate.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SEP — Stock equity prices (daily OHLCV, split-adjusted)
    # -------------------------------------------------------------------------

    def equity_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SEP",
            ticker=self._tickers_str(tickers),
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SFP — Fund/ETF prices (daily OHLCV)
    # -------------------------------------------------------------------------

    def fund_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SFP",
            ticker=self._tickers_str(tickers),
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # TICKERS — Company/fund descriptors
    # table param: "SEP" (equities), "SFP" (funds)
    # -------------------------------------------------------------------------

    def tickers(
        self,
        table: str = "SEP",
        tickers: str | list[str] | None = None,
        is_delisted: bool | None = None,
    ) -> pd.DataFrame:
        params: dict = {"table": table}
        if tickers is not None:
            params["ticker"] = self._tickers_str(tickers)
        if is_delisted is not None:
            params["isdelisted"] = "Y" if is_delisted else "N"
        return self._get("TICKERS", **params)

    # -------------------------------------------------------------------------
    # DAILY — Daily market metrics (EV, market cap, PE, PB, PS, EV/EBITDA)
    # -------------------------------------------------------------------------

    def daily_metrics(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "DAILY",
            ticker=self._tickers_str(tickers),
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # METRICS — Technical/risk metrics (beta, returns, 52w high/low, MAs, volume)
    # -------------------------------------------------------------------------

    def market_metrics(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "METRICS",
            ticker=self._tickers_str(tickers),
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # EVENTS — Earnings and corporate event dates
    # -------------------------------------------------------------------------

    def events(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "EVENTS",
            ticker=self._tickers_str(tickers),
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # ACTIONS — Corporate actions (splits, dividends, spin-offs)
    # -------------------------------------------------------------------------

    def corporate_actions(
        self,
        tickers: str | list[str] | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "ACTIONS",
            ticker=self._tickers_str(tickers),
            action=action,
            **{"date.gte": start_date, "date.lte": end_date},
        )

    # -------------------------------------------------------------------------
    # SP500 — S&P 500 constituent history (additions and removals)
    # -------------------------------------------------------------------------

    def sp500_history(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self._get(
            "SP500",
            **{"date.gte": start_date, "date.lte": end_date},
        )
