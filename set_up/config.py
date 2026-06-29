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
    import database.market.tickers_repo as tickers_repo

    return tickers_repo.get_universe_tickers(include_delisted)
