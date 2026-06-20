# QuorumNexus

A daily systematic trading system for US equities using relative strength momentum signals filtered through LLM-based entry analysis.

## Overview

QuorumNexus runs once per trading day and executes a three-phase loop:

1. **Sell** — evaluate open positions against stop-loss, profit target, trailing stop, and time-stop rules
2. **Optimize** — update trailing stops based on new highs
3. **Buy** — screen the S&P 500 universe for momentum setups, analyze candidates with a local LLM, and size new positions

The system is built around a single strategy: **Relative Strength Momentum (SA-RS)**, which finds stocks in strong uptrends that are setting up for a breakout, pullback re-entry, or MACD crossover.

## Architecture

```
main.py
└── PMAgent
    ├── SellAgent          — exit logic (stops, targets, time)
    ├── RSMomentumAgent    — signal generation + LLM analysis
    │   ├── MomentumFactorsModel   — loads pre-computed indicators from DB
    │   └── SA-RS system prompt    — qwen3:14b (local via Ollama)
    └── StrategyReceiver   — PM gate (gpt-4o, remote)
        └── PositionSizer  — risk-based position sizing
```

```
database/         PostgreSQL — OHLCV, indicators, descriptors, fundamentals
raw_data/         Alpaca market data + FRED macro fetchers
processed_data/   compute_indicators(), fundamentals transforms
signals/          Factor models: momentum, sector rotation, value, quality, growth
agents/           PMAgent, analyst agents, LLM client
runs/             positions_book.json, trade_log.json (runtime state)
```

## Strategy: Relative Strength Momentum

### Prefilter (runs on prior-day DB data — fast)
- **Gate 0** Cross-sectional rank: top 30% by 12-1 month momentum
- **Gate 1** Short-term RS: 20d return > 75th percentile, outperforming SPY and sector ETF
- **Gate 2** Trend health: above SMA-200 and SMA-50, r² > 0.65, positive slope
- **Gate 3** Entry signal (OR logic):
  - *Breakout*: within 3% of 20d high + volume ratio > 1.5
  - *Pullback*: price within -5% to +3% of SMA-20 + tight consolidation
  - *Crossover*: MACD histogram positive + 5d momentum > 20d momentum

### Analysis (runs on today's live data — per candidate)
Candidates are re-evaluated with intraday data. A local LLM (qwen3:14b) verifies that Gate 3 conditions still hold and scores each setup on a confidence ladder (0.0–1.0). Only candidates scoring ≥ 0.65 proceed to the PM gate.

### PM Gate
A second LLM call (gpt-4o) makes a final BUY / PASS decision based on the analyst's full reasoning.

### Position Sizing
Risk-based: 2× ATR stop distance, 3:1 reward/risk target, max 10% of NAV per position.

## Setup

### Prerequisites
- Python 3.11+
- Docker + Docker Compose (provides TimescaleDB + pgvector, Redis, MinIO)
- [Ollama](https://ollama.com) with `qwen3:14b` pulled
- Alpaca paper trading account
- OpenAI API key

### Install

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"     # dependencies live in pyproject.toml
cp .env.example .env         # then fill in API keys
```

### Bring up infrastructure & schema

```bash
make infra      # start db (TimescaleDB+pgvector), redis, minio
make migrate    # apply Alembic migrations  (== alembic upgrade head)
```

The database schema is managed entirely by **Alembic** (`migrations/`). There
are no `create_table` calls in application code — `alembic upgrade head` builds
every table from scratch, and migrations are versioned and reversible.

### Initial Data Load

With the schema applied, populate the tables with historical data:

```bash
python load_data.py
```

## Daily Workflow

### After market close (automated)
```bash
python daily_update.py
```
Updates OHLCV and recomputes indicators for all symbols. Set this up as a cron job:
```
0 18 * * 1-5 cd /path/to/QuorumNexus && venv/bin/python daily_update.py
```

### Before/at market open
```bash
python main.py
```
Runs the full sell → optimize → buy loop. Takes ~10 minutes (dominated by LLM calls for candidates).

## Configuration

`config.py` — universe of symbols (S&P 500 + sector ETFs)

Key parameters in `pm_agent.py`:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_pct` | 10% | Max NAV per position |
| `max_hold_days` | 10–20d | Per signal type |

Key parameters in `sa_RS.py` `prefilter()`:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `top_cs_pct` | 0.30 | Top 30% by CS momentum rank |
| `min_rs_percentile` | 75 | 20d return percentile floor |
| `min_r_squared` | 0.65 | Trend quality floor |
| `max_per_sector` | 3 | Concentration limit |

## Runtime State

Two JSON files track live trading state:

- `runs/positions_book.json` — open positions with stop/target/entry metadata
- `runs/trade_log.json` — completed trade history with P&L

Do not delete these while positions are open.

## Models

| Role | Model | Notes |
|------|-------|-------|
| Analyst (SA-RS) | `qwen3:14b` | Local via Ollama, ~50s per candidate |
| PM gate | `gpt-4o` | Remote OpenAI, billed per call |

To swap the analyst model at runtime:
```python
pm.set_analysts_model("qwen3:7b")  # faster, lower quality
```
