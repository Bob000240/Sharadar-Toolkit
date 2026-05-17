import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo
import pandas as pd
import numpy as np

class MomentumFactors:
    def __init__(self, start_date, end_date):
        self.start_date = start_date
        self.end_date = end_date
        self.weight = np.array([0.25, 0.25, 0.2, 0.15, 0.15])
    def compute_factors(self, symbol):
        pass
    def training(self):
        pass



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

def volume_ratio_momentum(mkt_series):
    return z_score(mkt_series)

def rsi_momentum(rsi_series):
    return z_score(rsi_series)