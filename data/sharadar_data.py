"""Thin client for the Nasdaq Data Link Sharadar datatables.

One method per vendor table, each translating keyword arguments into the API's
filter dicts. Nothing here interprets or reshapes the data; the signal layer
owns that.

The module patches a connect and read timeout onto the vendor library at import,
because its client otherwise waits indefinitely and an unattended daily update
would hang rather than fail.
"""

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
    """Authenticated access to the Sharadar tables.

    One method per table: ``fundamentals``, ``insider_transactions``,
    ``institutional_holdings``, ``equity_prices``, ``fund_prices``, ``tickers``,
    and ``events``. Every method paginates by default.
    """

    def __init__(self):
        """Read NDL_APIKEY from the environment and configure the client.

        Raise ValueError when the key is absent, rather than failing later on the first
        request with an authentication error.
        """
        self.key = os.getenv("NDL_APIKEY")
        if not self.key:
            raise ValueError("NDL_APIKEY not set")
        nasdaqdatalink.ApiConfig.api_key = self.key

    def _params(self, **kwargs) -> dict:
        """Drop the arguments left as None, which the API treats as absent."""
        return {k: v for k, v in kwargs.items() if v is not None}

    def _date_range(self, start: str | None, end: str | None) -> dict | None:
        """Build the API's gte/lte range dict, or None when both bounds are absent."""
        r = {}
        if start is not None:
            r["gte"] = start

        if end is not None:
            r["lte"] = end
        return r or None

    def fundamentals(
        self,
        tickers: str | list[str] | None = None,
        dimension: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch SF1 fundamentals.

        ``dimension`` selects the reporting basis, ``start_date`` and ``end_date`` bound
        the period reported on, and ``lastupdated_since`` bounds when the row last
        changed, which is what drives incremental loads.
        """
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

    def insider_transactions(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch SF2 insider transactions, bounded by filing date."""
        return nasdaqdatalink.get_table(
            "SHARADAR/SF2",
            **self._params(
                ticker=tickers, filingdate=self._date_range(start_date, end_date)
            ),
            paginate=paginate,
        )

    def institutional_holdings(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch SF3 institutional holdings, bounded by the quarter reported on."""
        return nasdaqdatalink.get_table(
            "SHARADAR/SF3",
            **self._params(
                ticker=tickers, calendardate=self._date_range(start_date, end_date)
            ),
            paginate=paginate,
        )

    def equity_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch SEP equity bars, bounded by date or by last change."""
        return nasdaqdatalink.get_table(
            "SHARADAR/SEP",
            **self._params(
                ticker=tickers,
                date=self._date_range(start_date, end_date),
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )

    def tickers(
        self,
        table: str = "SEP",
        tickers: str | list[str] | None = None,
        is_delisted: bool | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch ticker descriptors for one vendor table.

        ``table`` selects the vendor table, SEP for equities and SFP for funds.
        Filtering on ``is_delisted`` happens locally, since the API does not expose it.
        """
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

    def events(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch corporate event codes, bounded by date."""
        return nasdaqdatalink.get_table(
            "SHARADAR/EVENTS",
            **self._params(ticker=tickers, date=self._date_range(start_date, end_date)),
            paginate=paginate,
        )

    def fund_prices(
        self,
        tickers: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lastupdated_since: str | None = None,
        paginate=True,
    ) -> pd.DataFrame:
        """Fetch SFP fund bars, bounded by date or by last change."""
        return nasdaqdatalink.get_table(
            "SHARADAR/SFP",
            **self._params(
                ticker=tickers,
                date=self._date_range(start_date, end_date),
                lastupdated=self._date_range(lastupdated_since, None),
            ),
            paginate=paginate,
        )
