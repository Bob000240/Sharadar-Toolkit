import database.sentiment_repository as sentiment_repo
import database.market_repository as market_repo
import pandas as pd
from dataclasses import dataclass


@dataclass
class SentimentSnapshot:
    # Identity
    symbol: str
    signal_day: pd.Timestamp
    price: float

    # Analyst ratings (fractions 0–1)
    analyst_buy_pct:         float
    analyst_hold_pct:        float
    analyst_sell_pct:        float
    analyst_consensus_score: float      # 0=strong sell, 0.5=hold, 1=strong buy
    rating_change_direction: str        # "upgrade", "downgrade", "no_change"

    # Price target
    price_target_mean:   float
    price_target_high:   float
    price_target_low:    float
    price_target_upside: float          # (mean_target - price) / price

    # News & social sentiment
    news_sentiment_score: float         # -1=very negative, 0=neutral, +1=very positive
    sentiment_trend_20d:  float         # change in news_sentiment_score over 20 days

    # Short interest
    short_interest_pct:   float         # % of float sold short
    short_interest_ratio: float         # days-to-cover

    @staticmethod
    def _pct(v: float) -> str:
        return f"{v:+.1%}"

    @staticmethod
    def _rank(v: float) -> str:
        return f"{v:.0f}th percentile"

    def _fmt_header(self) -> str:
        upside_note = "upside" if self.price_target_upside > 0 else "downside"
        consensus_label = (
            "STRONG BUY"  if self.analyst_consensus_score >= 0.8 else
            "BUY"         if self.analyst_consensus_score >= 0.6 else
            "HOLD"        if self.analyst_consensus_score >= 0.4 else
            "SELL"        if self.analyst_consensus_score >= 0.2 else
            "STRONG SELL"
        )
        return "\n".join([
            f"SENTIMENT ANALYSIS - {self.symbol} | Signal date: {self.signal_day}",
            f"Current price: ${self.price:.2f} | Analyst consensus: {consensus_label} ({self.analyst_consensus_score:.2f}/1.0)",
            f"Mean price target: ${self.price_target_mean:.2f}  ({self._pct(self.price_target_upside)} {upside_note})",
        ])

    def _fmt_analyst_ratings(self) -> str:
        change_note = {
            "upgrade":    "recent UPGRADE — analysts becoming more bullish",
            "downgrade":  "recent DOWNGRADE — analysts becoming more cautious",
            "no_change":  "no recent rating change",
        }.get(self.rating_change_direction, self.rating_change_direction)
        return "\n".join([
            "--- ANALYST RATINGS ---",
            f"  Buy:  {self.analyst_buy_pct:.0%}  |  Hold: {self.analyst_hold_pct:.0%}  |  Sell: {self.analyst_sell_pct:.0%}",
            f"  Consensus score:  {self.analyst_consensus_score:.2f}  (0=strong sell, 0.5=hold, 1=strong buy)",
            f"  Rating change:    {change_note}",
        ])

    def _fmt_price_target(self) -> str:
        return "\n".join([
            "--- PRICE TARGET ---",
            f"  Mean target:   ${self.price_target_mean:.2f}  ({self._pct(self.price_target_upside)} vs current price)",
            f"  Target range:  ${self.price_target_low:.2f} – ${self.price_target_high:.2f}",
        ])

    def _fmt_news_sentiment(self) -> str:
        score_note = (
            "positive" if self.news_sentiment_score > 0.2 else
            "negative" if self.news_sentiment_score < -0.2 else
            "neutral"
        )
        trend_note = "improving" if self.sentiment_trend_20d > 0 else "deteriorating"
        return "\n".join([
            "--- NEWS & SOCIAL SENTIMENT ---",
            f"  Sentiment score:     {self.news_sentiment_score:+.2f}  ({score_note}; range: -1 to +1)",
            f"  20-day trend:        {self.sentiment_trend_20d:+.2f}  ({trend_note} over past month)",
        ])

    def _fmt_short_interest(self) -> str:
        squeeze_risk = (
            "elevated squeeze risk" if self.short_interest_ratio > 5 else
            "moderate" if self.short_interest_ratio > 3 else
            "low squeeze risk"
        )
        return "\n".join([
            "--- SHORT INTEREST ---",
            f"  Short interest (% float):  {self.short_interest_pct:.1%}  (>10% = heavily shorted)",
            f"  Days-to-cover ratio:       {self.short_interest_ratio:.1f}  ({squeeze_risk}; >5 = high squeeze potential)",
        ])

    def to_agent_prompt(self) -> str:
        return "\n\n".join([
            self._fmt_header(),
            self._fmt_analyst_ratings(),
            self._fmt_price_target(),
            self._fmt_news_sentiment(),
            self._fmt_short_interest(),
        ])


class SentimentFactorsModel:
    def __init__(
        self,
        signal_day: pd.Timestamp,
        stock_symbols: list[str] | str,
    ):
        self.signal_day = signal_day
        self.stock_symbols = [stock_symbols] if isinstance(stock_symbols, str) else stock_symbols
        self.stock_data = None
        self._load_data()

    def _load_data(self):
        sentiment = sentiment_repo.get_latest_sentiment(self.stock_symbols, self.signal_day)
        ohlcv = market_repo.get_latest_OHLCV(self.stock_symbols, self.signal_day)

        sentiment = sentiment.set_index("symbol")
        ohlcv = ohlcv.set_index("symbol")

        sentiment["price"] = ohlcv["close"]
        sentiment["price_target_upside"] = (
            (sentiment["price_target_mean"] - sentiment["price"]) / sentiment["price"]
        )

        self.stock_data = sentiment

    def get(self, symbol: str, col: str):
        if symbol not in self.stock_data.index:
            raise ValueError(f"Symbol {symbol} not in data")
        if col not in self.stock_data.columns:
            raise ValueError(f"Column {col} not in data")
        return self.stock_data.loc[symbol, col]

    def build_snapshot(self, symbol: str) -> SentimentSnapshot:
        return SentimentSnapshot(
            symbol=symbol,
            signal_day=self.signal_day,
            price=self.get(symbol, "price"),
            analyst_buy_pct=self.get(symbol, "analyst_buy_pct"),
            analyst_hold_pct=self.get(symbol, "analyst_hold_pct"),
            analyst_sell_pct=self.get(symbol, "analyst_sell_pct"),
            analyst_consensus_score=self.get(symbol, "analyst_consensus_score"),
            rating_change_direction=self.get(symbol, "rating_change_direction"),
            price_target_mean=self.get(symbol, "price_target_mean"),
            price_target_high=self.get(symbol, "price_target_high"),
            price_target_low=self.get(symbol, "price_target_low"),
            price_target_upside=self.get(symbol, "price_target_upside"),
            news_sentiment_score=self.get(symbol, "news_sentiment_score"),
            sentiment_trend_20d=self.get(symbol, "sentiment_trend_20d"),
            short_interest_pct=self.get(symbol, "short_interest_pct"),
            short_interest_ratio=self.get(symbol, "short_interest_ratio"),
        )


if __name__ == "__main__":
    symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]
    signal_day = pd.Timestamp.today()
    model = SentimentFactorsModel(signal_day, symbols)
    for sym in symbols:
        print(model.build_snapshot(sym).to_agent_prompt())
        print()
