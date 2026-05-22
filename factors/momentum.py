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
    """Raw momentum data for a single stock, formatted for AI agent interpretation."""

    symbol: str
    signal_day: str

    # Price returns
    return_1d: float
    return_5d: float
    return_20d: float
    return_60d: float
    return_252d: float

    # Benchmark-relative returns (vs SPY)
    excess_return_5d: float
    excess_return_20d: float

    # Sector-relative returns
    sector_relative_5d: float
    sector_relative_20d: float
    sector: str

    # Trend
    price: float
    sma_20: float
    sma_50: float
    sma_200: float
    above_sma_200: bool
    pct_from_52w_high: float

    # Momentum oscillators
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    macd_crossover: str  # "bullish", "bearish", "neutral"

    # Volume
    volume_ratio: float  # 10d avg / 50d avg
    obv_trend: str  # "rising", "falling", "flat"
    dollar_volume_20d_avg: float

    # Risk
    volatility_20: float
    atr_pct: float

    # Universe context
    return_5d_percentile: float  # 0-100, where stock ranks in S&P 500
    return_20d_percentile: float
    return_252d_percentile: float
    rsi_percentile: float

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
        all_indicator_df = indicator_repo.get_indicators(
            self.all_symbols, start_date=None, end_date=self.signal_day
        )
        all_ohlcv_df = market_repo.get_OHLCV(self.all_symbols, end_date=self.signal_day)

        if all_indicator_df.empty:
            raise ValueError("No indicator data found.")

        latest = all_indicator_df.sort_values("date").groupby("symbol").last()
        latest_close = (
            all_ohlcv_df.sort_values("date").groupby("symbol")["close"].last()
        )
        latest["close"] = latest_close

        # Split after fetching
        self.stock_data = latest.loc[self.stock_symbols]
        self.benchmark_data = latest.loc[[self.benchmark_symbol]]
        self.etf_data = latest.loc[self.etf_symbols]

        sector_df = self.get_sector_relative_returns(
            self.stock_symbols, self.signal_day
        )
        self.stock_data = self.stock_data.join(
            sector_df.set_index("symbol")[
                ["sector", "sector_relative_5d", "sector_relative_20d"]
            ]
        )

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

    def get_sector_relative_returns(self, symbols: list[str], signal_day: pd.Timestamp):
        if isinstance(symbols, str):
            symbols = [symbols]

        engine = db.get_connection()

        query = text("""
            WITH latest AS (
                SELECT DISTINCT ON (i.symbol)
                    i.symbol,
                    i.return_5d,
                    i.return_20d,
                    s.sector
                FROM indicators_data i
                JOIN sector_mapping s ON i.symbol = s.symbol
                WHERE i.symbol = ANY(:symbols)
                AND i.date <= :signal_day
                ORDER BY i.symbol, i.date DESC
            ),

            etf_latest AS (
                SELECT DISTINCT ON (s.sector)
                    s.sector,
                    i.return_5d  AS etf_return_5d,
                    i.return_20d AS etf_return_20d
                FROM indicators_data i
                JOIN sector_mapping s ON i.symbol = s.symbol
                WHERE i.symbol = ANY(:etf_symbols)
                AND i.date <= :signal_day
                ORDER BY s.sector, i.date DESC
            )

            SELECT
                l.symbol,
                l.sector,
                l.return_5d  - e.etf_return_5d  AS sector_relative_5d,
                l.return_20d - e.etf_return_20d AS sector_relative_20d
            FROM latest l
            JOIN etf_latest e ON l.sector = e.sector
            ORDER BY l.symbol
        """)

        params = {
            "symbols": symbols,
            "etf_symbols": self.etf_symbols,
            "signal_day": signal_day.date(),
        }

        return pd.read_sql_query(query, engine, params=params)

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError()
        if col not in self.stock_data.columns:
            raise ValueError()
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str):
        bench_5d = self.benchmark_data.loc[self.benchmark_symbol, "return_5d"]
        bench_20d = self.benchmark_data.loc[self.benchmark_symbol, "return_20d"]
        sector_bench_5d = self.stock_data.loc[symbol, "sector_relative_5d"]
        sector_bench_20d = self.stock_data.loc[symbol, "sector_relative_20d"]
        return MomentumSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            return_1d=self.get(symbol, "return_1d"),
            return_5d=self.get(symbol, "return_5d"),
            return_20d=self.get(symbol, "return_20d"),
            return_60d=self.get(symbol, "return_60d"),
            return_252d=self.get(symbol, "return_252d"),
            excess_return_5d=self.get(symbol, "return_5d") - bench_5d,
            excess_return_20d=self.get(symbol, "return_20d") - bench_20d,
            sector_relative_5d=self.get(symbol, "sector_relative_5d"),
            sector_relative_20d=self.get(symbol, "sector_relative_20d"),
            sector=self.get(symbol, "sector"),
            price=self.get(symbol, "close"),
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
