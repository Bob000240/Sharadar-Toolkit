import database.indicator_repository as indicator_repo
import database.sector_data_repository as sector_repo
import database.market_data_repository as market_repo
import database.db_connection as db
from sqlalchemy import text
import pandas as pd
from dataclasses import dataclass
from textwrap import dedent


@dataclass
class MomentumSnapshot:
    """Raw momentum data for a single stock."""

    # Identity
    symbol: str
    signal_day: str

    # Absolute momentum
    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float

    # Composite momentum
    momentum_composite_percentile: float
    momentum_consistency: float
    # Count of positive periods across 5d/20d/60d/252d (0–4)

    # Benchmark-relative momentum (vs SPY)
    excess_return_5d: float
    excess_return_20d: float

    # Sector-relative momentum
    sector_relative_5d: float
    sector_relative_20d: float
    sector: str

    # Trend / structure
    price: float
    above_sma_200: bool
    pct_from_52w_high: float
    new_52w_high: bool

    # Trend quality
    r_squared_60d: float
    # R² of price vs time regression (0–1)

    trend_slope_60d: float
    # Annualized regression slope over 60d

    slope_x_r2: float
    # trend_slope_60d * r_squared_60d

    drawdown_from_recent_high: float
    # Max drawdown over trailing 20d

    # Momentum acceleration
    momentum_accel_20_60: float
    # return_20d - return_60d

    momentum_accel_5_20: float
    # return_5d - return_20d

    # Volume / participation
    volume_ratio: float
    # 10d avg volume / 50d avg volume

    dollar_volume_20d_avg: float

    # Risk / volatility
    volatility_20: float
    atr_pct: float

    vol_adjusted_momentum: float
    # return_60d / volatility_20

    # Universe-relative ranks (0–100)
    return_5d_percentile: float
    return_20d_percentile: float
    return_60d_percentile: float
    return_252d_percentile: float


    # Market regime
    spy_above_sma_200: bool
    spy_return_20d_percentile: float

    # Breadth / regime quality
    sp500_pct_above_sma_200: float
    sp500_new_highs_ratio: float

    def to_agent_prompt(self) -> str:
        """
        Returns a plain-English summary of all momentum signals for the AI agent.
        Designed to be interpretable without any quant background.
        """
        sma_trend = _describe_sma_trend(
            self.price, self.sma_20, self.sma_50, self.sma_200
        )
        high_proximity = f"{self.pct_from_52w_high * 100:.1f}% below 52-week high"

        return dedent(f"""
                MOMENTUM ANALYSIS: {self.symbol} as of {self.signal_day}
                {"=" * 55}

                PRICE RETURNS
                1-day:    {self.return_1d * 100:+.2f}%
                5-day:    {self.return_5d * 100:+.2f}%  (top {100 - self.return_5d_percentile:.0f}% of S&P 500)
                20-day:   {self.return_20d * 100:+.2f}%  (top {100 - self.return_20d_percentile:.0f}% of S&P 500)
                60-day:   {self.return_60d * 100:+.2f}%
                252-day:  {self.return_252d * 100:+.2f}%  (top {100 - self.return_252d_percentile:.0f}% of S&P 500)

                RELATIVE PERFORMANCE
                vs SPY (5d):       {self.excess_return_5d * 100:+.2f}%  {"outperforming" if self.excess_return_5d > 0 else "underperforming"} the market
                vs SPY (20d):      {self.excess_return_20d * 100:+.2f}%  {"outperforming" if self.excess_return_20d > 0 else "underperforming"} the market
                vs Sector (5d):    {self.sector_relative_5d * 100:+.2f}%  {"outperforming" if self.sector_relative_5d > 0 else "underperforming"} {self.sector} peers
                vs Sector (20d):   {self.sector_relative_20d * 100:+.2f}%  {"outperforming" if self.sector_relative_20d > 0 else "underperforming"} {self.sector} peers

                TREND STRUCTURE
                Price vs moving averages: {sma_trend}
                Distance from 52-week high: {high_proximity}
                Above 200-day SMA: {"Yes — stock is in a long-term uptrend" if self.above_sma_200 else "No — stock is below its long-term trend"}

                MOMENTUM OSCILLATORS
                RSI (14):  {self.rsi_14:.1f}  ({_describe_rsi(self.rsi_14)}, top {100 - self.rsi_percentile:.0f}% of universe)
                MACD:      {self.macd:.4f} vs Signal {self.macd_signal:.4f} — histogram {self.macd_hist:+.4f} ({self.macd_crossover} momentum)

                VOLUME SIGNALS
                Volume ratio (10d/50d): {self.volume_ratio:.2f}x  ({_describe_volume(self.volume_ratio)})
                OBV trend: {self.obv_trend}
                Avg daily dollar volume: ${self.dollar_volume_20d_avg:,.0f}

                RISK PROFILE
                20-day volatility:  {self.volatility_20 * 100:.2f}% daily
                ATR as % of price:  {self.atr_pct * 100:.2f}%

                AGENT NOTES
                - {"Strong broad momentum: outperforming both market and sector." if self.excess_return_5d > 0 and self.sector_relative_5d > 0 else "Mixed relative performance — check if sector is dragging or stock is lagging peers."}
                - {"Volume is confirming the price move." if self.volume_ratio > 1.1 and self.obv_trend == "rising" else "Volume is NOT confirming the price move — treat momentum with caution."}
                - {"RSI is stretched — momentum may be exhausted short-term." if self.rsi_14 > 70 else "RSI is oversold — potential mean reversion risk." if self.rsi_14 < 30 else "RSI is in neutral territory."}
                - {"MACD is bullish — momentum is accelerating." if self.macd_crossover == "bullish" else "MACD is bearish — momentum is fading." if self.macd_crossover == "bearish" else "MACD is neutral."}
                """).strip()


class MomentumFactorsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str] | str,
        benchmark_symbol: str,
        etf_symbols: list[str] | str,
    ):
        self.signal_day = signal_day
        self.stock_symbols = stock_symbols
        self.benchmark_symbol = benchmark_symbol
        self.etf_symbols = etf_symbols

        self.all_symbols = (
            self.stock_symbols + [self.benchmark_symbol] + self.etf_symbols
        )

        self.stock_data = None
        self.benchmark_data = None
        self.sector_data = None
        self._load_data()

    def _load_data(self):
        # One DB call for everything
        all_ohlcv_df = market_repo.get_latest_OHLCV(self.all_symbols, self.signal_day)
        all_indicator_df = indicator_repo.get_latest_indicators(self.all_symbols, self.signal_day)

        if all_indicator_df.empty:
            raise ValueError("No indicator data found.")

        # Index by symbol so .loc[] works
        all_indicator_df = all_indicator_df.set_index("symbol")
        all_ohlcv_df = all_ohlcv_df.set_index("symbol")

        # Add close from OHLCV (not stored in indicators table)
        all_indicator_df["close"] = all_ohlcv_df["close"]

        # Split after fetching
        self.stock_data = all_indicator_df.loc[self.stock_symbols].copy()
        self.benchmark_data = all_indicator_df.loc[[self.benchmark_symbol]].copy()
        self.etf_data = all_indicator_df.loc[self.etf_symbols].copy()


        sector_map = sector_repo.get_sector_mapping(self.all_symbols).set_index("symbol")["sector"]
        self.stock_data["sector"] = sector_map.reindex(self.stock_data.index)
        self.etf_data["sector"] = sector_map.reindex(self.etf_data.index)

        etf_returns = self.etf_data.set_index("sector")[["return_5d", "return_20d"]]
        self.stock_data["sector_relative_5d"]  = self.stock_data["return_5d"]  - self.stock_data["sector"].map(etf_returns["return_5d"])
        self.stock_data["sector_relative_20d"] = self.stock_data["return_20d"] - self.stock_data["sector"].map(etf_returns["return_20d"])

        self.stock_data["momentum_composite_percentile"] = self.stock_data



        print("Data loaded successfully.")
        print(f"Stock data shape: {self.stock_data.shape}")
        print(f"Benchmark data shape: {self.benchmark_data.shape}")
        print("Sample stock data:")
        print(self.stock_data.head())
        print("Sample benchmark return_5d:")
        print(self.benchmark_data.loc[self.benchmark_symbol, "return_5d"])
        print("sample etf data:")
        print(self.etf_data.head())
        print("Sample stock columns:")
        print(self.stock_data.columns.to_list())

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError()
        if col not in self.stock_data.columns:
            raise ValueError()
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str):
        bench_5d = self.benchmark_data.loc[self.benchmark_symbol, "return_5d"]
        bench_20d = self.benchmark_data.loc[self.benchmark_symbol, "return_20d"]
        return MomentumSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,

            return_5d=self.get(symbol, "return_5d"),
            return_20d=self.get(symbol, "return_20d"),
            return_60d=self.get(symbol, "return_60d"),
            return_252d=self.get(symbol, "return_252d"),

            #momentum_composite_percentile
            momentum_consistency=sum([
                self.get(symbol, "return_5d") > 0,
                self.get(symbol, "return_20d") > 0,
                self.get(symbol, "return_60d") > 0,
                self.get(symbol, "return_252d") > 0,
            ]),

            excess_return_5d=self.get(symbol, "return_5d") - bench_5d,
            excess_return_20d=self.get(symbol, "return_20d") - bench_20d,

            sector_relative_5d=self.get(symbol, "sector_relative_5d"),
            sector_relative_20d=self.get(symbol, "sector_relative_20d"),
            sector=self.get(symbol, "sector"),

            price=self.get(symbol, "close"),
            above_sma_200=self.get(symbol, "above_sma_200"),
            pct_from_52w_high=self.get(symbol, "pct_from_52w_high"),
            new_52w_high=self.get(symbol, "new_52w_high"),

            r_squared_60d=self.get(symbol, "r_squared_60d"),
            trend_slope_60d=self.get(symbol, "trend_slope_60d"),
            slope_x_r2=self.get(symbol, "slope_x_r2"),
            drawdown_from_recent_high=self.get(symbol, "drawdown_from_recent_high"),

            momentum_accel_20_60=self.get(symbol, "momentum_accel_20_60"),
            momentum_accel_5_20=self.get(symbol, "momentum_accel_5_20"),

            volume_ratio=self.get(symbol, "volume_ratio"),
            dollar_volume_20d_avg=self.get(symbol, "dollar_volume_20d_avg"),

            volatility_20=self.get(symbol, "volatility_20"),
            atr_pct=self.get(symbol, "atr_pct"),
            vol_adjusted_momentum=self.get(symbol, "vol_adjusted_momentum"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    etf_symbol = [
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
    benchmark = "SPY"
    signal_day = pd.Timestamp.today()
    print(signal_day)

    agent = MomentumFactorsModel(signal_day, symbols, benchmark, etf_symbol)
    print(agent.get("NVDA", "return_5d"))
