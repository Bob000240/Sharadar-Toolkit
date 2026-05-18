import database.market_data_repository as market_repo
import database.indicator_repository as indicator_repo
import pandas as pd
import numpy as np

WEIGHTS = {
    "5d": 0.20,
    "20d": 0.20,
    "relative_5d": 0.20,
    "relative_20d": 0.15,
    "volume_ratio": 0.15,
    "rsi": 0.10
}

class MomentumFactorsModel:
    def __init__(self, signal_day, stock_symbols, benchmark_symbol):
        self.signal_day = signal_day
        self.stock_symbols = stock_symbols
        self.benchmark_symbol = benchmark_symbol
        self.stock_data = {}
        self.benchmark_data = None
        self._load_data()

    def _load_data(self):
        for symbol in self.stock_symbols:
            df = pd.DataFrame(
                indicator_repo.get_latest_indicators(symbol, self.signal_day)
            )

            if df.empty:
                raise ValueError(f"No data found for {symbol}")

            self.stock_data[symbol] = df

        self.benchmark_data = pd.DataFrame(
            indicator_repo.get_latest_indicators(
                self.benchmark_symbol,
                self.signal_day
            )
        )

        if self.benchmark_data.empty:
            raise ValueError(f"No benchmark data found for {self.benchmark_symbol}")

    def fetch_factor_series(self, column_name):
        factor_df = pd.DataFrame()

        for symbol in self.stock_symbols:
            s = self.stock_data[symbol].set_index("date")
            factor_df[symbol] = s[column_name]

        return factor_df.iloc[-1]

    def fetch_benchmark_value(self, column_name):
        return self.benchmark_data.set_index("date")[column_name].iloc[-1]

    def compute_5d(self):
        latest_return_5d = self.fetch_factor_series("return_5d")
        return five_days_momentum(latest_return_5d)

    def compute_20d(self):
        latest_return_20d = self.fetch_factor_series("return_20d")
        return twenty_days_momentum(latest_return_20d)

    def compute_relative_5d(self):
        latest_return_5d = self.fetch_factor_series("return_5d")
        benchmark_return_5d = self.fetch_benchmark_value("return_5d")
        return relative_five_days_momentum(latest_return_5d, benchmark_return_5d)

    def compute_relative_20d(self):
        latest_return_20d = self.fetch_factor_series("return_20d")
        benchmark_return_20d = self.fetch_benchmark_value("return_20d")
        return relative_twenty_days_momentum(latest_return_20d, benchmark_return_20d)

    def compute_volume_ratio(self):
        latest_volume_ratio = self.fetch_factor_series("volume_ratio")
        return volume_ratio_momentum(latest_volume_ratio)

    def compute_rsi(self):
        latest_rsi = self.fetch_factor_series("rsi_14")
        return rsi_momentum(latest_rsi)
    
    def compute_scores(self):
        factors = {
            "5d": self.compute_5d(),
            "20d": self.compute_20d(),
            "relative_5d": self.compute_relative_5d(),
            "relative_20d": self.compute_relative_20d(),
            "volume_ratio": self.compute_volume_ratio(),
            "rsi": self.compute_rsi()
        }
        score = sum(WEIGHTS[key] * value for key, value in factors.items())
        return score



def z_score(series):
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std

def five_days_momentum(ind_series):
    return z_score(ind_series)

def twenty_days_momentum(ind_series):
    return z_score(ind_series)

def relative_five_days_momentum(ind_series, benchmark_value):
    return z_score(ind_series - benchmark_value)


def relative_twenty_days_momentum(ind_series, benchmark_value):
    return z_score(ind_series - benchmark_value)

def volume_ratio_momentum(mkt_series):
    return z_score(mkt_series)

def rsi_momentum(rsi_series):
    return z_score(rsi_series)

if __name__ == "__main__":
    mf = MomentumFactorsModel(
        signal_day= pd.Timestamp.today(),
        stock_symbols=["NVDA", "AAPL", "MSFT"],
        benchmark_symbol="SPY"
    )

    scores = mf.compute_scores()
    print(scores)
    print("Best stock:", scores.idxmax())