# QuorumNexus — Deterministic Prefilter + Constrained Agentic Risk Manager

## Core concept

QuorumNexus is not an "AI picks stocks" system. It is a database-centered trading research system
where deterministic code decides which trades are eligible, defines the complete risk envelope, and
records every decision for audit and evaluation.

The agent is load-bearing only after the deterministic layer has narrowed the universe. Its job is
to choose among precomputed risk options, assess profit likelihood using approved tools and past
trade memory, explain the evidence, and recommend tighter risk management when warranted.

**Core rule:**

> Deterministic prefilter creates the trade envelope -> agent chooses within that envelope ->
> database records the decision and evidence -> eval tests whether the agent improves over defaults.

## Layer responsibilities

### 1. Deterministic layer: prefilter and risk envelope

The deterministic layer owns all numeric screening, eligibility, and hard risk controls.

It computes:

- OHLCV features, technical indicators, relative strength, volume and breakout metrics
- moving averages, volatility, ATR, liquidity, market cap, sector and industry context
- fundamental ratios such as revenue growth, EPS growth, debt/equity, margin, and valuation
- hard gates such as liquidity minimums, trend requirements, earnings proximity, and volatility
- a default stop, default target, and default timeline
- a list of allowed stop-loss choices
- a list of allowed target-price choices
- a list of allowed holding timelines
- position-size limits and maximum loss constraints

The output is a compact candidate packet. Example:

```json
{
  "symbol": "NVDA",
  "as_of_date": "2026-06-20",
  "profile_id": "momentum_growth",
  "prefilter_score": 82,
  "passed_gates": ["relative_strength", "volume_breakout", "revenue_growth"],
  "risk_flags": ["earnings_in_9_days"],
  "default_stop_id": "atr_2_0",
  "default_target_id": "r_multiple_2_0",
  "default_timeline_id": "10d",
  "stop_choices": [
    {"id": "atr_1_5", "price": 118.2, "max_loss_pct": 3.1},
    {"id": "atr_2_0", "price": 115.6, "max_loss_pct": 4.2}
  ],
  "target_choices": [
    {"id": "r_multiple_1_5", "price": 132.4},
    {"id": "r_multiple_2_0", "price": 137.1}
  ],
  "timeline_choices": [
    {"id": "5d", "max_holding_days": 5},
    {"id": "10d", "max_holding_days": 10}
  ]
}
```

The deterministic layer may reject a trade. The agent may not revive it.

### 2. Agentic layer: constrained risk selection and evidence judgment

The agent receives only eligible candidate packets. It does not re-score the numeric prefilter and
does not invent new risk levels.

The agent may:

- choose one stop from `stop_choices`
- choose one target from `target_choices`
- choose one timeline from `timeline_choices`
- choose a smaller position size than the deterministic maximum
- pass on the trade
- recommend an earlier or tighter exit
- estimate profit likelihood based on memory and evidence
- explain uncertainty and cite evidence IDs

The agent may not:

- enter a trade rejected by the deterministic prefilter
- create a looser stop than the deterministic choices allow
- exceed position-size limits
- create targets outside the deterministic choices
- bypass hard risk flags or liquidity gates
- query arbitrary SQL
- place uncontrolled orders

The agent output is a structured verdict:

```json
{
  "symbol": "NVDA",
  "direction": "BUY",
  "profit_likelihood": 0.63,
  "confidence": 0.71,
  "selected_stop_id": "atr_1_5",
  "selected_target_id": "r_multiple_2_0",
  "selected_timeline_id": "10d",
  "position_size_multiplier": 0.75,
  "rationale": "Similar momentum-growth setups performed best with tighter ATR stops when earnings were inside two weeks.",
  "tools_called": ["search_similar_setups", "get_recent_filing_events", "get_portfolio_context"],
  "evidence_ids": ["memory_42", "filing_event_8"]
}
```

### 3. Database layer: source of truth and decision memory

The database stores deterministic features, candidate packets, agent verdicts, evidence links, and
resolved trade outcomes. It is the spine of the system.

Core tables:

- `companies`
- `market_bars`
- `technical_indicators`
- `fundamentals_snapshots`
- `prefilter_profiles`
- `screened_candidates`
- `decision_memory`
- `trade_outcomes`
- `eval_results`

Optional later SEC/evidence tables:

- `filings`
- `filing_chunks`
- `filing_events`

The important invariant is point-in-time correctness. Any retrieval used by the agent must only see
information available at the decision date.

```sql
WHERE filing_date <= decision_date
  AND resolution_date < decision_date
```

For fundamentals, store both `period_end` and `filing_date`. The filing date is what controls
knowledge availability.

### 4. Eval layer: prove whether the agent adds lift

The eval layer measures whether the agent's choices beat deterministic defaults.

It should answer:

- Did agent-selected stops outperform the default stop?
- Did agent-selected targets improve expectancy?
- Did agent-selected timelines reduce drawdown or missed upside?
- Were `profit_likelihood` estimates calibrated?
- Did similar-trade memory improve results versus no-memory decisions?
- Did the agent reduce losses by passing on weak prefilter candidates?

A null result is valid. If the agent performs the same as the deterministic baseline, the system has
still learned something useful.

## Tool boundary

The agent only gets narrow, typed tools:

- `get_live_snapshot`
- `search_similar_setups`
- `get_recent_trade_memory`
- `get_portfolio_context`
- `run_mini_backtest`
- `search_sec_evidence` later or fixture-backed first
- `get_recent_filing_events` later or fixture-backed first

No arbitrary SQL and no raw database access.

## Source routing

The source does not decide the layer. The form of the data does.

| Data | Layer | Use |
|---|---|---|
| OHLCV and indicators | Deterministic | gates, scores, stops, targets, timelines |
| Fundamental ratios | Deterministic | gates and risk flags |
| Earnings dates | Deterministic | event-risk flags |
| Past trade outcomes | Database + agentic retrieval | similar setup memory |
| Filing metadata/event type | Deterministic or typed flag | risk flag |
| Filing prose/news/prose evidence | Agentic | catalyst and risk interpretation |

FMP remains the preferred source for structured fundamentals. SEC EDGAR is optional later for prose,
filing metadata, and event evidence.

## Current design target

The first complete milestone is:

> One eligible candidate enters the system, receives a deterministic risk menu, gets an agent verdict
> choosing stop/target/timeline/size within that menu, writes to decision memory, and later resolves
> into an outcome that can be evaluated against the default.

That loop matters more than broad ingestion at the beginning.
