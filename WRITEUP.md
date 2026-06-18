# QuorumNexus — Project Write-Up

## Motivation

Most retail algorithmic trading systems fall into one of two failure modes. The first is over-engineering: elaborate multi-factor models with dozens of signals that fit historical data beautifully and generalize poorly. The second is under-engineering: a simple moving average crossover running on a broker's script editor with no risk management and no edge.

QuorumNexus is an attempt at a third path: a disciplined, single-strategy system with a small number of well-understood signals, explicit position sizing and exit rules, and an LLM layer that acts as a qualitative sanity check rather than a black box decision maker. The goal is not to maximize Sharpe in backtests — it is to build something robust enough to run live with real capital.

The strategy is **Relative Strength Momentum**. The thesis is simple: stocks that are already outperforming the market on a 1–12 month basis tend to continue outperforming in the near term. This is one of the most well-documented anomalies in equity markets, present across geographies and time periods. The system's job is to find the best-positioned names within that universe and enter them at technically sound moments.

---

## Strategy Design

### Why Momentum?

Cross-sectional momentum (buying recent winners, avoiding recent losers) has been documented in academic literature since Jegadeesh and Titman (1993). The 12-1 month lookback — using 12 months of return but skipping the most recent month to avoid short-term reversal — is the canonical construction. It is not a secret edge. What matters is the implementation: which stocks you pick from the momentum universe, when you enter, how you size, and how you exit.

### The Prefilter

The prefilter runs on four sequential gates, each designed to eliminate a different class of bad candidate:

**Gate 0 — Cross-sectional rank.** Restricts the universe to the top 30% of S&P 500 stocks by 12-1 month momentum. This ensures you are only looking at genuinely strong recent performers, not just stocks that passed a loose threshold.

**Gate 1 — Short-term relative strength.** Requires the stock to be outperforming SPY and its sector ETF on a 20-day basis. This filters out momentum stocks that are stalling or rotating into weakness relative to the market. A stock can have strong 12-month momentum but be deteriorating over the past month — Gate 1 catches that.

**Gate 2 — Trend health.** Requires the stock to be above its 200-day and 50-day moving averages, with a 60-day price regression showing R² > 0.65 and a positive slope. The R² filter is important: it excludes stocks with strong returns but chaotic price paths (high volatility names that happened to spike). A high R² means the stock has been rising in a consistent, linear fashion — the kind of trend that tends to persist.

**Gate 3 — Entry timing.** Passing Gates 0-2 means the stock is fundamentally strong on momentum metrics. Gate 3 asks: is now a good time to buy? It accepts any of three patterns:
- *Breakout*: price near its 20-day high with above-average volume (trend continuation)
- *Pullback*: price has pulled back to near its 20-day SMA with tight consolidation (dip buy in an uptrend)
- *Crossover*: MACD histogram just turned positive and short-term momentum is accelerating (momentum re-ignition)

The OR logic in Gate 3 is intentional. Each signal represents a different entry philosophy, and requiring only one of them keeps the candidate pool large enough to find actionable setups daily while still requiring a concrete timing reason.

### Why Not Just Run the Prefilter?

The prefilter alone would generate a mechanical buy list every morning. The problem is that systematic signals computed from prior-day closing data are stale by the time the market opens. A breakout signal from yesterday's close might have already faded — or the stock might have gapped up 4% at open, changing the risk/reward entirely. The two-stage LLM analysis layer exists to bridge this gap.

---

## The LLM Layer

### Design Philosophy

The LLMs in this system are not making predictions. They are performing a structured evaluation of whether a pre-qualified setup still looks actionable given today's intraday data. This is an important distinction.

A momentum signal computed from historical data has already done the heavy lifting. The LLM's job is narrower: verify that the Gate 3 condition still holds with today's numbers, check for obvious conflicts (overbought RSI, negative MACD on a pullback setup, volume below threshold), and output a calibrated confidence score.

This is closer to a checklist than a prediction. LLMs are well-suited to this task because the evaluation requires reading a structured data snapshot and applying explicit criteria — exactly the kind of instruction-following task where modern models are reliable.

### Two-Stage Pipeline

**Stage 1 — SA-RS (Strategy Agent: Relative Strength)**

The analyst agent receives a full momentum snapshot for the candidate: returns across multiple timeframes, trend quality metrics, oscillators, breakout/pullback signals, EMA crossover status, and volume data. It is given the prefilter criteria, the active signal mode, and a detailed rubric for evaluating each signal type.

The system prompt enforces a confidence ladder with explicit decision rules. Rather than asking the LLM to decide freely, it is told: if two or more key indicators are not confirming, cap confidence at 0.64. If the Gate 3 condition no longer holds with today's data, output AVOID. The mapping from confidence to direction (BUY / WAIT / AVOID) is deterministic — the LLM only has to get the confidence number right.

The model used is `qwen3:14b` running locally via Ollama. A local model was chosen deliberately: no per-call cost, no latency variance from API rate limits, and the ability to run without internet access during market hours.

**Stage 2 — StrategyReceiver (PM Gate)**

Candidates that score bullish with confidence ≥ 0.65 in Stage 1 are passed to a second LLM call using GPT-4o. This agent plays the role of a portfolio manager reviewing analyst recommendations. It reads the full analyst reasoning and makes a final BUY or PASS decision with a one-sentence rationale.

The two-stage design reflects a real portfolio management workflow: an analyst does the detailed work, a PM makes the allocation decision. The PM gate catches cases where the analyst reasoning is technically correct but the trade is still not compelling — perhaps because the stock is already too large a position, or the rationale doesn't survive a second read.

### Data Freshness

A key architectural decision: the prefilter runs on prior-day pre-computed indicators stored in a PostgreSQL database, while the LLM analysis runs on today's intraday data fetched only for the filtered candidates.

This two-phase approach dramatically reduces runtime. Computing indicators from raw OHLCV data for all 515 symbols every morning took over two minutes. Reading from the database takes seconds. The live data fetch — which matters for the timing signals — is then only done for the handful of candidates (typically 5–15), not the full universe.

The tradeoff: the prefilter gates are evaluated on prior-day prices, so a stock that was near its 20-day high yesterday might have already broken out (and be extended) by the time the system runs. The LLM is explicitly instructed to account for this — it is told that Gate 3 conditions were measured on prior-day close and must be re-verified with today's snapshot.

---

## Risk Management

### Entry
Position size is determined by the 2× ATR (Average True Range) stop distance. The system risks a fixed percentage of NAV per trade by dividing the dollar risk allocation by the per-share stop distance. This means larger, more volatile positions get fewer shares, not just a proportional NAV allocation.

### Exits
Four exit conditions are checked daily against live prices:

1. **Stop loss** — price crosses the stop level (set at entry as 2× ATR below price)
2. **Partial target** — price reaches the 3:1 target (6× ATR above price); half the position is sold and the stop is moved to breakeven
3. **Full target** — price reaches the 3:1 target a second time (after partial exit); remaining shares are sold
4. **Time stop** — position is held beyond its maximum hold period (10–20 days depending on signal type) regardless of P&L

The trailing stop updates the stop level when the stock makes a new high, using the same 2× ATR distance. This locks in profit on strong movers without cutting winners prematurely.

The partial exit at the 3:1 target is designed to let the system participate in large moves while booking partial gains on stocks that reverse after a strong initial run.

---

## Implementation Notes

### Database
All market data, computed indicators, sector descriptors, and fundamental data are stored in PostgreSQL. The indicator table stores one row per symbol per day with ~40 pre-computed columns. Keeping this data local avoids re-fetching from Alpaca on every run and enables the fast prefilter.

### Daily Update
A separate `daily_update.py` script runs after market close to fetch new OHLCV data and update indicators. This keeps the database current so the morning run can use yesterday's close without any computation.

### Broker Integration
Order execution uses the Alpaca paper trading API. All orders are market orders with DAY time-in-force. The system currently runs in paper mode; switching to live trading requires changing a single flag.

---

## What This Is Not

QuorumNexus is not a backtested system with a validated edge. The strategy is based on well-documented momentum principles, and the implementation is designed to be rigorous, but live performance will differ from any backtest. Momentum strategies are known to have periods of significant drawdown (momentum crashes), typically during sharp market reversals.

The LLM layer adds a qualitative filter that has no historical track record. It is designed to reduce false positives from the systematic prefilter, but it introduces model-specific behavior that is difficult to validate before running live.

The system is appropriate for paper trading and strategy development. Any transition to live capital should be preceded by a meaningful paper trading period and a clear understanding of the strategy's risk profile.

---

## Future Work

- **Backtesting framework** — validate the prefilter gates and entry signals against historical data before committing capital
- **Additional strategies** — the architecture supports multiple analyst agents (`sa_RS`, potentially `sa_Value`, `sa_Quality`); the PM agent is designed to receive verdicts from multiple strategies
- **Sector rotation overlay** — `sig_sector_rotation.py` is built but not yet wired into the buy decision; strong sector tailwinds could be used to weight confidence scores
- **Performance tracking** — the trade log captures all exits with P&L; building a performance dashboard would help identify which signal types (breakout / pullback / crossover) are generating the best returns
