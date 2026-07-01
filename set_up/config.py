from functools import lru_cache

BENCHMARK_SYMBOLS = [
    "SPY",
    "XLK",
    "XLY",
    "XLC",
    "XLF",
    "XLV",
    "XLI",
    "XLE",
    "XLB",
    "XLRE",
    "XLU",
    "XLP",
]

# Sector names MUST match the `sector` values stored in the tickers table
# (Sharadar/Zacks taxonomy), otherwise sector joins/lookups silently produce NaN.
ETF_SECTOR_MAP = {
    "XLK": "Technology",
    "XLY": "Consumer Cyclical",
    "XLC": "Communication Services",
    "XLF": "Financial Services",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLE": "Energy",
    "XLB": "Basic Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLP": "Consumer Defensive",
}


@lru_cache(maxsize=2)
def get_stock_symbols(include_delisted: bool = False) -> list[str]:
    """Return the database-backed tradeable stock universe for the current run."""
    import pandas as pd
    from sqlalchemy import text

    from database.db_connection import get_connection

    delisted_filter = "" if include_delisted else "AND t.isdelisted = 'N'"
    query = text(f"""
        SELECT t.ticker
        FROM tickers AS t
        JOIN LATERAL (
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY prices.dollar_volume
                ) AS median_dollar_volume_20d
            FROM (
                SELECT ep.close * ep.volume AS dollar_volume
                FROM equity_prices AS ep
                WHERE ep.ticker = t.ticker
                  AND ep.date <= CURRENT_DATE
                  AND ep.close > 0
                  AND ep.volume >= 0
                ORDER BY ep.date DESC
                LIMIT 20
            ) AS prices
            HAVING COUNT(*) >= 15
        ) AS liquidity ON TRUE
        WHERE t.table_code = 'SEP'
          {delisted_filter}
          AND t.currency = 'USD'
          AND t.exchange IN ('NYSE', 'NASDAQ')
          AND t.category LIKE 'Domestic Common Stock%'
          AND t.category NOT LIKE '%Secondary%'
          AND liquidity.median_dollar_volume_20d >= 5000000
        ORDER BY t.ticker
    """)
    return pd.read_sql_query(query, get_connection())["ticker"].tolist()
