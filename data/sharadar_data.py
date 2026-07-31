import os
import pandas as pd
from dotenv import load_dotenv
import nasdaqdatalink
from nasdaqdatalink.connection import Connection as _NDLConnection

load_dotenv()

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30

if not getattr(_NDLConnection, "_qn_timeout_patched", False):
    _orig_execute_request = _NDLConnection.execute_request.__func__

    def _execute_request_with_timeout(cls, http_verb, url, **options):
        options.setdefault("timeout", (_CONNECT_TIMEOUT, _READ_TIMEOUT))
        return _orig_execute_request(cls, http_verb, url, **options)

    _NDLConnection.execute_request = classmethod(_execute_request_with_timeout)
    _NDLConnection._qn_timeout_patched = True


class SharadarData:
    def __init__(self):
        self.key = os.getenv("NDL_APIKEY")
        if not self.key:
            raise ValueError("NDL_APIKEY not set")
        nasdaqdatalink.ApiConfig.api_key = self.key

    def _params(self, **kwargs) -> dict:
        return {k: v for k, v in kwargs.items() if v is not None}

    def _date_range(self, start: str | None, end: str | None) -> dict | None:
        r = {}
        if start is not None:
            r["gte"] = start

        if end is not None:
            r["lte"] = end
        return r or None

    # `lastupdated_since` below filters on the sync watermark: the date Sharadar
    # last WROTE the row, which is not the row's own date. It is the only filter
    # that surfaces revisions to old periods (SF1 restatements, SEP split
    # re-adjustments). Available on SEP/SFP/SF1/TICKERS only — SF2/SF3/EVENTS
    # don't expose it. Passing None omits the filter entirely.

    # -------------------------------------------------------------------------
    # SF1 -- income statement, balance sheet, and cash flow data for US equities,
    #        sourced from SEC filings (10-K, 10-Q).
    # -------------------------------------------------------------------------

    def fundamentals(
        self,
        tickers: str | list[str] | None = None,
        dimension: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/SF1",
            **self._params(
                ticker=tickers,
                dimension=dimension,
                calendardate=self._date_range(start_date, end_date),
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )

    # -------------------------------------------------------------------------
    # SF2 -- Insider transactions (Form 4)
    # -------------------------------------------------------------------------

    def insider_transactions(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/SF2",
            **self._params(
                ticker=tickers, filingdate=self._date_range(start_date, end_date)
            ),
            paginate=paginate,
        )

    # -------------------------------------------------------------------------
    # SF3 -- Institutional holdings by ticker
    # -------------------------------------------------------------------------

    def institutional_holdings(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/SF3",
            **self._params(
                ticker=tickers, calendardate=self._date_range(start_date, end_date)
            ),
            paginate=paginate,
        )

    # -------------------------------------------------------------------------
    # SEP -- Stock equity prices (daily OHLCV, split-adjusted)
    # -------------------------------------------------------------------------

    def equity_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/SEP",
            **self._params(
                ticker=tickers,
                date=self._date_range(start_date, end_date),
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )

    # -------------------------------------------------------------------------
    # TICKERS -- Company/fund descriptors
    # table: "SEP" (equities), "SFP" (funds)
    # -------------------------------------------------------------------------

    def tickers(
        self,
        table: str = "SEP",
        tickers: str | list[str] | None = None,
        is_delisted: bool | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        df = nasdaqdatalink.get_table(
            "SHARADAR/TICKERS",
            **self._params(
                table=table,
                ticker=tickers,
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )
        if is_delisted is not None:
            flag = "Y" if is_delisted else "N"
            df = df[df["isdelisted"] == flag]
        return df.reset_index(drop=True)

    # -------------------------------------------------------------------------
    # EVENTS -- Earnings and corporate event dates
    # -------------------------------------------------------------------------

    def events(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/EVENTS",
            **self._params(ticker=tickers, date=self._date_range(start_date, end_date)),
            paginate=paginate,
        )

    # -------------------------------------------------------------------------
    # SFP -- Fund/ETF prices (daily OHLCV)
    # -------------------------------------------------------------------------

    def fund_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        return nasdaqdatalink.get_table(
            "SHARADAR/SFP",
            **self._params(
                ticker=tickers,
                date=self._date_range(start_date, end_date),
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )


if __name__ == "__main__":
    sh = SharadarData()

    print("--- SF1: Fundamentals ---")
    fundamentals = sh.fundamentals(
        tickers=["AAPL", "NVDA"], start_date="2020-01-01", end_date="2020-12-31"
    )
    print(fundamentals)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    print("--- SF2: Insider Transactions ---")
    insiders = sh.insider_transactions(
        tickers=["AAPL", "NVDA"], start_date="2020-01-01", end_date="2020-12-31"
    )
    print(insiders)

    print("--- SF3: Institutional Holdings ---")
    institutions = sh.institutional_holdings(
        tickers=["AAPL", "NVDA"], start_date="2020-01-01", end_date="2020-12-31"
    )
    print(institutions)

    print("--- SEP: Equity Prices ---")
    prices = sh.equity_prices(
        tickers=["AAPL", "NVDA"], start_date="2020-01-01", end_date="2020-01-10"
    )
    print(prices)

    print("--- TICKERS: Company Descriptors ---")
    descriptors = sh.tickers(table="SEP", tickers=["AAPL", "NVDA"], is_delisted=False)
    print(descriptors)

    print("--- EVENTS: Corporate Events ---")
    events = sh.events(
        tickers=["AAPL", "NVDA"], start_date="2020-01-01", end_date="2020-12-31"
    )
    print(events)

    print("--- SFP: Fund Prices ---")
    fund_prices = sh.fund_prices(
        tickers=["SPY", "QQQ"], start_date="2020-01-01", end_date="2020-01-10"
    )
    print(fund_prices)
