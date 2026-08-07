"""Read-only eligibility queries: the point-in-time tradeable universe per strategy.

Unlike the other repositories in this package, this module owns no table and
stores nothing — `setup_db` never touches it. Each strategy gets its own
`<strategy>_eligible_tickers(signal_day)` function that joins the already-populated
market tables (tickers, equity_prices, fundamentals, technical_features) and
returns the tickers clearing that strategy's fixed eligibility definition.

A strategy's eligibility thresholds are baked into its own function here rather
than passed in — the whole universe definition is one cohesive unit. Add a new
function when a new strategy needs a different one.
"""

import pandas as pd
from sqlalchemy import text

from database.db_connection import get_connection


_SL_MIN_DOLLAR_VOLUME = 5_000_000
_SL_MIN_MARKET_CAP = 10_000_000_000
_SL_MIN_RETURN_60D = 0
_SL_MIN_RETURN_252D = 0


def SL_eligible_tickers(signal_day) -> pd.DataFrame:
    """sector_leaders' eligible universe as of `signal_day`, one row per ticker
    with its PIT market cap. All filters are point-in-time:

      - listing: NYSE/NASDAQ, USD, domestic common, non-secondary
      - liquidity: median dollar volume over the last 20 sessions >= $5M,
        with >=15 of those sessions present
      - recency: traded within 10 days of signal_day (the survivorship/zombie
        guard — not an isdelisted flag)
      - size: latest SF1 ART market cap >= $1B
      - profitability: SF1 ART common net income > 0
      - trend: return_60d > 0, return_252d > 0, close > sma_200, and a currently
        rising 60-day slope (return_60d alone can stay positive while the trend
        has already rolled over within the window)

    Both SF1 lookups filter on `datekey` (the filing date), never `calendardate`
    (a normalization label that can be a future period end).
    """
    as_of = pd.Timestamp(signal_day).date().isoformat()
    query = text("""
        SELECT t.ticker, funda.marketcap
        FROM tickers AS t
        JOIN LATERAL (
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY prices.dollar_volume
                ) AS median_dollar_volume_20d,
                MAX(prices.date) AS last_traded
            FROM (
                SELECT ep.date, ep.close * ep.volume AS dollar_volume
                FROM equity_prices AS ep
                WHERE ep.ticker = t.ticker
                  AND ep.date <= :as_of
                  AND ep.close > 0
                  AND ep.volume >= 0
                ORDER BY ep.date DESC
                LIMIT 20
            ) AS prices
            HAVING COUNT(*) >= 15
        ) AS liquidity ON TRUE
        JOIN LATERAL (
            SELECT f.marketcap, f.netinccmnusd
            FROM fundamentals AS f
            WHERE f.ticker = t.ticker
              AND f.dimension = 'ART'
              AND f.datekey <= CAST(:as_of AS date)
            ORDER BY f.datekey DESC
            LIMIT 1
        ) AS funda ON TRUE
        JOIN LATERAL (
            SELECT tf.close, tf.sma_200, tf.return_60d, tf.return_252d,
                   tf.trend_slope_60d
            FROM technical_features AS tf
            WHERE tf.ticker = t.ticker
              AND tf.date <= CAST(:as_of AS date)
            ORDER BY tf.date DESC
            LIMIT 1
        ) AS technical ON TRUE
        WHERE t.table_code = 'SEP'
          AND t.currency = 'USD'
          AND t.exchange IN ('NYSE', 'NASDAQ')
          AND t.category LIKE 'Domestic Common Stock%'
          AND t.category NOT LIKE '%Secondary%'
          AND liquidity.median_dollar_volume_20d >= :min_dollar_volume
          AND liquidity.last_traded >= CAST(:as_of AS date) - 10
          AND funda.marketcap >= :min_market_cap
          AND funda.netinccmnusd > 0
          AND technical.return_60d > :min_return_60d
          AND technical.return_252d > :min_return_252d
          AND technical.close > technical.sma_200
          AND technical.trend_slope_60d > 0
        ORDER BY t.ticker
    """)
    return pd.read_sql_query(
        query,
        get_connection(),
        params={
            "as_of": as_of,
            "min_dollar_volume": _SL_MIN_DOLLAR_VOLUME,
            "min_market_cap": _SL_MIN_MARKET_CAP,
            "min_return_60d": _SL_MIN_RETURN_60D,
            "min_return_252d": _SL_MIN_RETURN_252D,
        },
    )
