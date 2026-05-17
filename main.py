from data_collection.market_data import MarketData
import derived_features.indicators as indicators
import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo

if __name__ == "__main__":
    symbols = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "JPM", "AVGO", "LLY",
        "XOM", "UNH", "V", "MA", "COST", "JNJ", "PG", "HD", "WMT", "ABBV",
        "BAC", "KO", "NFLX", "ORCL", "CVX", "MRK", "CRM", "AMD", "CSCO", "PEP",
        "TMO", "ACN", "MCD", "ADBE", "LIN", "WFC", "DHR", "ABT", "DIS", "TXN",
        "VZ", "INTU", "QCOM", "AMGN", "PM", "CAT", "GE", "IBM", "NOW", "INTC",
        "RTX", "SPGI", "HON", "UNP", "LOW", "BKNG", "ISRG", "GS", "BLK", "PLD",
        "AXP", "T", "SYK", "ELV", "PGR", "DE", "MDT", "GILD", "AMAT", "TJX",
        "ADI", "LRCX", "SCHW", "MMC", "MO", "CB", "ETN", "ADP", "VRTX", "CI",
        "REGN", "C", "ZTS", "SO", "TMUS", "DUK", "BDX", "SLB", "CVS", "BSX",
        "PANW", "FI", "CME", "MU", "CL", "EOG", "MCK", "EQIX", "SHW", "AON",
        "ICE", "NOC", "WM", "ITW", "APD", "MPC", "SNPS", "KLAC", "CDNS", "CMG",
        "PH", "APH", "FDX", "HCA", "ORLY", "EMR", "PSA", "MSI", "MAR", "PNC",
        "RSG", "ADSK", "TT", "WELL", "ROP", "AIG", "COF", "PAYX", "TRV", "CTAS",
        "AZO", "MET", "ROST", "D", "AFL", "CARR", "MS", "NSC", "PCAR", "JCI",
        "IDXX", "NXPI", "GIS", "OXY", "ALL", "AMP", "FICO", "TEL", "FAST", "KMB",
        "TGT", "EA", "SRE", "CMI", "CPRT", "KMI", "CTSH", "AME", "HAL", "BKR",
        "OTIS", "ODFL", "YUM", "HUM", "EXC", "LHX", "PRU", "DHI", "VLO", "CSX",
        "DFS", "DG", "NEM", "PXD", "ADM", "AEP", "KR", "PEG", "MNST", "DLR",
        "BIIB", "XEL", "ED", "WMB", "MTD", "CTVA", "FANG", "SBAC", "ROK", "VICI",
        "RMD", "MCHP", "HPQ", "WEC", "AWK", "ANET", "GWW", "STZ", "CHTR", "ECL",
        "PPG", "DLTR", "KEYS", "PCG", "FTNT", "KHC", "HES", "EBAY", "ALB", "NUE",
        "CBRE", "VRSK", "WTW", "LEN", "DOW", "DD", "EXR", "EFX", "IRM", "IFF",
        "TTWO", "WST", "MTB", "FITB", "BRO", "CNC", "TSCO", "CAH", "DTE", "LYB",
        "FIS", "GLW", "A", "PPL", "HBAN", "ES", "FE", "EIX", "INVH", "RF",
        "DRI", "STE", "MKC", "LULU", "ETR", "WAT", "VMC", "EXPE", "PFG", "CMS",
        "CLX", "HIG", "LH", "MLM", "TYL", "COO", "HOLX", "MOH", "ZBH", "ULTA",
        "NDAQ", "WAB", "TRMB", "STT", "SWK", "AKAM", "AVB", "NVR", "DGX", "PKG",
        "BBY", "BALL", "CF", "ATO", "LVS", "RJF", "WRB", "GEN", "OMC", "TXT",
        "J", "CINF", "BAX", "TER", "K", "IP", "MAS", "HRL", "L", "SNA",
        "POOL", "PODD", "FDS", "ARE", "UDR", "NI", "JKHY", "ESS", "MRO", "EPAM",
        "NRG", "CE", "HPE", "FMC", "CBOE", "CAG", "HAS", "CTLT", "CHD", "NDSN",
        "AEE", "AES", "ALGN", "APA", "BF.B", "BXP", "CPB", "DAY", "DOC", "EVRG",
        "FFIV", "FOX", "FOXA", "GNRC", "HSY", "INCY", "IPG", "JNPR", "KIM", "LKQ",
        "MGM", "MOS", "MTCH", "NTRS", "PAYC", "PNR", "PTC", "QRVO", "RL", "RVTY",
        "SOLV", "SWKS", "TECH", "TFX", "UHS", "VTR", "WY", "ZBRA"
    ]
    start_date = "2020-02-01"
    end_date = "2026-04-30"
    '''
    market_repo.drop_OHLCV_table()
    market_repo.create_OHLCV_table()
    for symbol in symbols:
        market_repo.insert_OHLCV_table(MarketData().get_OHLCV(symbol, start_date, end_date))

    indicator_repo.drop_indicators_table()
    indicator_repo.create_indicators_table()
    for symbol in symbols:
        df = market_repo.get_OHLCV(symbol, start_date, end_date)
        df = indicators.compute_trading_indicators(df)
        indicator_repo.insert_indicators(df)
    '''
    df_apple = indicator_repo.get_indicators("AAPL", start_date, end_date)
    print(df_apple.sort_values("date", ascending=False).head())
