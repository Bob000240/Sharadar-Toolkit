"""Shared pipeline constants.

``BENCHMARK_SYMBOLS`` are the fund tickers loaded alongside equities: SPY as the
broad-market benchmark and the SPDR sector ETFs. They live in the fund price
table rather than the equity one, so they are fetched separately.
"""

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
