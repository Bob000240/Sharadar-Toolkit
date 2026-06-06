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

# ~50 liquid large-caps across 5 sectors — expand to S&P 500 once pipeline is proven
STOCK_SYMBOLS = [
    # Technology (XLK)
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD",
    "ADBE", "CSCO", "ORCL", "CRM", "INTC",

    # Financials (XLF)
    "JPM", "BAC", "GS", "MS", "V",
    "MA", "BLK", "AXP", "C", "BX",

    # Healthcare (XLV)
    "UNH", "JNJ", "LLY", "ABBV", "MRK",
    "TMO", "ABT", "DHR", "AMGN", "MDT",

    # Industrials (XLI)
    "CAT", "DE", "HON", "GE", "RTX",
    "LMT", "ETN", "EMR", "UPS", "NOC",

    # Energy (XLE)
    "XOM", "CVX", "COP", "SLB", "EOG",
    "OXY", "PSX", "VLO", "MPC", "HAL",
]

ALL_SYMBOLS = STOCK_SYMBOLS + BENCHMARK_SYMBOLS
