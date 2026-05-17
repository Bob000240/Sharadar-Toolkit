import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo
import pandas as pd

def z_score(series):
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std

def five_day_momentum(ind_series):
    return z_score(ind_series)

def twenty_day_momentum(ind_series):
    return z_score(ind_series)

def sector_twenty_day_momentum(sector_ind_series):
    return z_score(sector_ind_series)

def volume_ratio_momentum(mkt_series, sector_mkt_series):
    return z_score(mkt_series / sector_mkt_series)

def rsi_momentum(rsi_series):
    return z_score(rsi_series)