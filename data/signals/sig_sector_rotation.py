import database.indicator_repository as indicator_repo
import pandas as pd
from dataclasses import dataclass

SECTOR_ETF_MAP = {
    "XLK":  "Technology",
    "XLV":  "Healthcare",
    "XLF":  "Financial Services",
    "XLY":  "Consumer Cyclical",
    "XLP":  "Consumer Defensive",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLI":  "Industrials",
    "XLB":  "Basic Materials",
    "XLRE": "Real Estate",
    "XLC":  "Communication Services",
}

CYCLICAL_SECTORS  = {"Technology", "Consumer Cyclical", "Communication Services",
                     "Financial Services", "Industrials", "Energy"}
DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare",
                     "Real Estate", "Basic Materials"}
