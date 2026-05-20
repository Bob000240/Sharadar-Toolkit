import database.indicator_repository as indicator_repo
import pandas as pd

WEIGHTS = {
    "5d": 0.20,
    "20d": 0.20,
    "relative_5d": 0.20,
    "relative_20d": 0.15,
    "volume_ratio": 0.15,
    "rsi": 0.10
}

class MomentumFactorsModel:
    def __init__(self, signal_day: pd.Timestamp, stock_symbols: list[str], benchmark_symbol: str):
        self.signal_day = signal_day
        self.stock_symbols = stock_symbols
        self.benchmark_symbol = benchmark_symbol
        self.stock_data = None
        self.benchmark_data = None
        self._load_data()

    def _load_data(self):
        df = indicator_repo.get_indicators(
            self.stock_symbols,
            start_date=None,
            end_date=self.signal_day
        )

        if df.empty:
            raise ValueError("No indicator data found for given symbols")

        self.stock_data = (
            df.sort_values("date")
            .groupby("symbol")
            .last()
        )

        bench_df = indicator_repo.get_indicators(
            self.benchmark_symbol,
            start_date=None,
            end_date=self.signal_day
        )

        if bench_df.empty:
            raise ValueError(f"No benchmark data found for {self.benchmark_symbol}")

        self.benchmark_data = bench_df.sort_values("date").iloc[-1]

    def fetch_factor_series(self, column_name: str) -> pd.Series:
        # stock_data is now indexed by symbol directly
        return self.stock_data.loc[self.stock_symbols, column_name]

    def fetch_benchmark_value(self, column_name: str) -> float:
        return self.benchmark_data[column_name]

    def compute_5d(self):
        return five_days_momentum(self.fetch_factor_series("return_5d"))

    def compute_20d(self):
        return twenty_days_momentum(self.fetch_factor_series("return_20d"))

    def compute_relative_5d(self):
        return relative_five_days_momentum(
            self.fetch_factor_series("return_5d"),
            self.fetch_benchmark_value("return_5d")
        )

    def compute_relative_20d(self):
        return relative_twenty_days_momentum(
            self.fetch_factor_series("return_20d"),
            self.fetch_benchmark_value("return_20d")
        )

    def compute_volume_ratio(self):
        return volume_ratio_momentum(self.fetch_factor_series("volume_ratio"))

    def compute_rsi(self):
        return rsi_momentum(self.fetch_factor_series("rsi_14"))

    def compute_scores(self):
        factors = {
            "5d":          self.compute_5d(),
            "20d":         self.compute_20d(),
            "relative_5d": self.compute_relative_5d(),
            "relative_20d":self.compute_relative_20d(),
            "volume_ratio":self.compute_volume_ratio(),
            "rsi":         self.compute_rsi()
        }
        score = pd.Series(0.0, index=self.stock_symbols)
        for key, value in factors.items():
            score += WEIGHTS[key] * value
        return score

def z_score(series: pd.Series, clip: float = 3.0):
    mean = series.mean()
    std = series.std(ddof=1)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return ((series - mean) / std).clip(-clip, clip)

def five_days_momentum(ind_series: pd.Series):
    return z_score(ind_series)

def twenty_days_momentum(ind_series: pd.Series):
    return z_score(ind_series)

def relative_five_days_momentum(ind_series: pd.Series, benchmark_value: float):
    return z_score(ind_series - benchmark_value)

def relative_twenty_days_momentum(ind_series: pd.Series, benchmark_value: float):
    return z_score(ind_series - benchmark_value)

def volume_ratio_momentum(mkt_series: pd.Series):
    return z_score(mkt_series)

def rsi_momentum(rsi_series: pd.Series):
    return z_score(rsi_series - 50)


if __name__ == "__main__":
    mf = MomentumFactorsModel(
        signal_day=pd.Timestamp.today(),
        stock_symbols=["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"],
        benchmark_symbol="SPY"
    )
    scores = mf.compute_scores()
    print(scores)
    print("Best stock:", scores.idxmax())