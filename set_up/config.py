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


# Market-cap buckets (USD), classified on a point-in-time market cap. Boundaries
# mirror the bands used in sig_fundamentals.valuation() (mid 1B–10B, large ≥10B);
# the 300M floor drops nano/micro caps, which every strategy's universe excludes.
_MICRO_CAP_CEILING = 300_000_000
_MID_CAP_FLOOR = 1_000_000_000
_LARGE_CAP_FLOOR = 10_000_000_000


def cap_bucket(marketcap) -> str | None:
    """small / mid / large for a point-in-time market cap; None for nano/micro or
    missing (which the strategies exclude)."""
    if marketcap is None or marketcap != marketcap or marketcap < _MICRO_CAP_CEILING:
        return None
    if marketcap >= _LARGE_CAP_FLOOR:
        return "large"
    if marketcap >= _MID_CAP_FLOOR:
        return "mid"
    return "small"
