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
