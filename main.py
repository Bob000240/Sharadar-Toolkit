from data_collection.market_data import MarketData
from data_collection.sector_data import get_sector
from derived_features.indicators import compute_indicators
import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo
import database.sector_data_repository as sector_repo
import pandas as pd

def initial_filter(symbols: list[str]) -> list[str]:
    selections = []
    for symbol in symbols:
        df = indicator_repo.get_latest_indicators(symbol, pd.Timestamp("2026-05-19"))
        row = df.iloc[0]
        try:
            ma_test = row["above_sma_200"]
            vr_test = row["volume_ratio"] > 1
            rsi_test = 30 < row["rsi_14"] < 70
            if ma_test and vr_test and rsi_test:
                selections.append(symbol)
        except KeyError as e:
            print(f"Missing indicator for {symbol}: {e}")
            continue

    return selections


if __name__ == "__main__":
    symbols = [
        "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
        "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL", "GOOGL",
        "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG", "AMT", "AWK",
        "AMP", "AME", "AMGN", "APH", "ADI", "AON", "APA", "APO", "AAPL", "AMAT",
        "APP", "APTV", "ACGL", "ADM", "ARES", "ANET", "AJG", "AIZ", "T", "ATO",
        "ADSK", "ADP", "AZO", "AVB", "AVY", "AXON", "BKR", "BALL", "BAC", "BAX",
        "BDX", "BRK.B", "BBY", "TECH", "BIIB", "BLK", "BX", "XYZ", "BK", "BA",
        "BKNG", "BSX", "BMY", "AVGO", "BR", "BRO", "BF.B", "BLDR", "BG", "BXP",
        "CHRW", "CDNS", "CPT", "CPB", "COF", "CAH", "CCL", "CARR", "CVNA", "CASY",
        "CAT", "CBOE", "CBRE", "CDW", "COR", "CNC", "CNP", "CF", "CRL", "SCHW",
        "CHTR", "CVX", "CMG", "CB", "CHD", "CIEN", "CI", "CINF", "CTAS", "CSCO",
        "C", "CFG", "CLX", "CME", "CMS", "KO", "CTSH", "COHR", "COIN", "CL",
        "CMCSA", "FIX", "CAG", "COP", "ED", "STZ", "CEG", "COO", "CPRT", "GLW",
        "CPAY", "CTVA", "CSGP", "COST", "CRH", "CRWD", "CCI", "CSX", "CMI", "CVS",
        "DHR", "DRI", "DDOG", "DVA", "DECK", "DE", "DELL", "DAL", "DVN", "DXCM",
        "FANG", "DLR", "DG", "DLTR", "D", "DPZ", "DASH", "DOV", "DOW", "DHI",
        "DTE", "DUK", "DD", "ETN", "EBAY", "SATS", "ECL", "EIX", "EW", "EA",
        "ELV", "EME", "EMR", "ETR", "EOG", "EPAM", "EQT", "EFX", "EQIX", "EQR",
        "ERIE", "ESS", "EL", "EG", "EVRG", "ES", "EXC", "EXE", "EXPE", "EXPD",
        "EXR", "XOM", "FFIV", "FDS", "FICO", "FAST", "FRT", "FDX", "FIS", "FITB",
        "FSLR", "FE", "F", "FTNT", "FTV", "FOXA", "FOX", "BEN", "FCX",
        "GRMN", "IT", "GE", "GEHC", "GEV", "GEN", "GNRC", "GD", "GIS", "GM",
        "GPC", "GILD", "GPN", "GL", "GDDY", "GS", "HAL", "HIG", "HAS", "HCA",
        "DOC", "HSIC", "HSY", "HPE", "HLT", "HOLX", "HD", "HON", "HRL", "HST",
        "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII", "IBM", "IEX", "IDXX", "ITW",
        "INCY", "IR", "PODD", "INTC", "IBKR", "ICE", "IFF", "IP", "INTU", "ISRG",
        "IVZ", "INVH", "IQV", "IRM", "JBHT", "JBL", "JKHY", "J", "JNJ", "JCI",
        "JPM", "KVUE", "KDP", "KEY", "KEYS", "KMB", "KIM", "KMI", "KKR", "KLAC",
        "KHC", "KR", "LHX", "LH", "LRCX", "LVS", "LDOS", "LEN", "LII", "LLY",
        "LITE", "LIN", "LYV", "LKQ", "LMT", "L", "LOW", "LULU", "LYB", "MTB",
        "MPC", "MKTX", "MAR", "MMC", "MLM", "MAS", "MA", "MTCH", "MKC", "MCD",
        "MCK", "MDT", "MRK", "META", "MET", "MTD", "MGM", "MCHP", "MU", "MSFT",
        "MAA", "MRNA", "MHK", "MOH", "TAP", "MDLZ", "MPWR", "MNST", "MCO", "MS",
        "MOS", "MSI", "MSCI", "NDAQ", "NTAP", "NFLX", "NEM", "NWSA", "NWS", "NEE",
        "NKE", "NI", "NDSN", "NSC", "NTRS", "NOC", "NCLH", "NRG", "NUE", "NVDA",
        "NVR", "NXPI", "ORLY", "OXY", "ODFL", "OMC", "ON", "OKE", "ORCL", "OTIS",
        "PCAR", "PKG", "PLTR", "PANW", "PH", "PAYX", "PAYC", "PYPL", "PNR",
        "PEP", "PFE", "PCG", "PM", "PSX", "PNW", "PNC", "POOL", "PPG", "PPL",
        "PFG", "PG", "PGR", "PLD", "PRU", "PEG", "PTC", "PSA", "PHM", "PWR",
        "QCOM", "DGX", "RL", "RJF", "RTX", "O", "REG", "REGN", "RF",
        "RSG", "RMD", "RVTY", "HOOD", "ROK", "ROL", "ROP", "ROST", "RCL", "SPGI",
        "CRM", "SNDK", "SBAC", "SLB", "STX", "SRE", "NOW", "SHW", "SPG", "SWKS",
        "SJM", "SW", "SNA", "SOLV", "SO", "LUV", "SWK", "SBUX", "STT", "STLD",
        "STE", "SYK", "SMCI", "SYF", "SNPS", "SYY", "TMUS", "TROW", "TTWO", "TPR",
        "TRGP", "TGT", "TEL", "TDY", "TER", "TSLA", "TXN", "TPL", "TXT", "TMO",
        "TJX", "TKO", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC", "TYL", "TSN",
        "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI", "UNH", "UHS",
        "VLO", "VEEV", "VTR", "VLTO", "VRSN", "VRSK", "VZ", "VRTX", "VRT", "VTRS",
        "VICI", "V", "VST", "VMC", "WRB", "GWW", "WAB", "WMT", "DIS", "WBD",
        "WM", "WAT", "WEC", "WFC", "WELL", "WST", "WDC", "WY", "WSM", "WMB",
        "WTW", "WDAY", "WYNN", "XEL", "XYL", "YUM", "ZBRA", "ZBH", "ZTS"]
    benchmark_symbol = ["SPY", "XLK" , "XLY", "XLC", "XLF", "XLV", "XLI", "XLE", "XLB", "XLRE", "XLU", "XLP"]
    all_symbols = symbols + benchmark_symbol
    start_date = "2025-01-01"
    end_date = pd.Timestamp.today()

    market_repo.drop_OHLCV_table()
    market_repo.create_OHLCV_table()
    market_repo.insert_OHLCV_table(MarketData().get_OHLCV(all_symbols, start_date, end_date))
    
    indicator_repo.drop_indicators_table()
    indicator_repo.create_indicators_table()

    sector_repo.drop_sector_mapping_table()
    sector_repo.create_sector_mapping_table()

    for symbol in all_symbols:
        print(f"Processing {symbol}")

        df = market_repo.get_OHLCV(symbol, start_date, end_date)
        df = compute_indicators(df)

        if "symbol" not in df.columns:
            print(f"ERROR: symbol column missing for {symbol}")
            print(df.columns)
            break

        if df["symbol"].isna().any():
            print(f"ERROR: symbol contains NaN for {symbol}")
            break

        indicator_repo.insert_indicators(df)

    
    sector_repo.insert_sector_mapping(get_sector(all_symbols))
    
    df = market_repo.get_OHLCV(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = indicator_repo.get_indicators(["SPY", "AAPL"], start_date, end_date)
    print(df.sort_values("date", ascending=False).head())
    df = sector_repo.get_sector_mapping(["SPY", "AAPL"])
    print(df)

    print(initial_filter(symbols))

