# QuorumNexus — Build Strategy

## Goal

Build the deterministic spine first, then make the agent useful inside strict risk boundaries.

The project succeeds when QuorumNexus can prove whether an evidence-aware agent improves trade
management over deterministic defaults. The target is not an unconstrained trading oracle. The target
is an auditable system where every agent choice can be compared against the default stop, target,
timeline, and pass/enter decision.

## Chosen Architecture

QuorumNexus follows a professional portfolio-management separation of duties:

- signal/research models find opportunities
- portfolio construction decides sizing and allocation
- risk systems enforce hard limits
- execution systems place orders
- the agent acts like a bounded PM/trader inside the mandate

The agent can express conviction, but deterministic systems enforce the risk mandate.

### Deterministic Signal Layer

All active deterministic prefilters run before the agent.

Each prefilter is a signal/research model. For example:

- `pre_RS`: relative-strength momentum prefilter
- future value, breakout, reversal, quality-growth, or event-driven prefilters

Each passing prefilter emits a candidate packet with:

- symbol and decision date
- prefilter/profile ID
- setup score
- passed gates
- risk flags
- default stop loss
- default target price
- default holding timeline
- allowed stop choices
- allowed target choices
- allowed timeline choices
- maximum position size
- maximum loss
- relevant backtest/walk-forward stats

The agent cannot create a candidate for a prefilter that did not pass.

### Agentic PM Layer

The agent receives candidate packets from all passing prefilters.

Before making a decision, the agent must use typed tools to fetch agentic evidence, such as:

- prefilter backtest and walk-forward performance
- similar past trades
- recent trade memory
- current portfolio exposure
- current signal and market context
- mini-backtest results
- optional filing/news/evidence context

The agent decides:

- whether to accept or reject the trade
- which prefilter-generated candidate packet to use when multiple packets exist
- which allowed stop to use
- which allowed target to use
- which allowed timeline to use
- conviction tier
- estimated profit likelihood and confidence
- which evidence supports the decision

The conviction tier controls position size and risk budget:

- `HIGH_CONVICTION`: full allowed size
- `CONVICTION`: reduced size
- `LOW_CONVICTION`: small size
- `REJECT`: no position

The agent may reduce risk through conviction tier, but it cannot exceed deterministic maximum size,
maximum loss, or portfolio exposure limits.

### Deterministic Risk Layer

The deterministic risk layer validates every agent verdict.

It enforces:

- maximum position size
- maximum loss
- liquidity limits
- volatility limits
- sector and portfolio exposure limits
- correlation/concentration limits
- allowed stop, target, and timeline IDs
- no trade unless a deterministic prefilter passed
- no uncontrolled orders

The risk layer may reject or reduce an agent-approved trade.

### Execution Layer

The execution layer only receives validated orders.

It places trades, tracks positions, applies stops and targets, and records lifecycle events.

### Database and Eval Layer

The database records:

- candidate packets
- tool calls
- evidence IDs
- agent verdicts
- selected stop, target, timeline, and conviction tier
- realized outcomes

The eval layer compares agent-managed trades against deterministic defaults:

- default stop versus selected stop
- default target versus selected target
- default timeline versus selected timeline
- full-size default versus conviction-adjusted sizing
- agent accept/reject decisions versus prefilter baseline
- calibration of profit likelihood

## Build order

### Phase 0 — Data foundation and architecture inventory

Define the deterministic data foundation the prefilters will use. This phase maps what exists, what
will be added, which source owns each dataset, where it is stored, and which signal modules feed the
prefilters.

| Domain | Current Source | Future/Target Source | Current Code | Storage | Feed Medium | Status |
|---|---|---|---|---|---|---|
| Equity OHLCV | Alpaca | Alpaca / Sharadar / Schwab if needed | `data_det/raw_data/market_data.py` | `OHLCV_data` | `sig_technicals` | Exists |
| Fundamentals | FMP | Sharadar | `data_det/raw_data/fundamentals_data.py` | quality/value/growth fundamentals | `sig_fundamentals` | Exists, source will change |
| Company descriptors | FMP/profile data | Sharadar or other reference source | `data_det/raw_data/descriptors_data.py` | descriptors table | `sig_fundamentals`, `sig_sector_rotation` | Exists |
| Macro | FRED | FRED | `data_det/raw_data/macro_data.py` | macro table | `sig_macro` | Exists |
| Technical indicators | Internal calculation | Internal calculation | `data_det/processed_data/indicators.py` | indicators table | `sig_technicals` | Exists |
| Insider transactions | Not implemented | Sharadar / SEC / other source | TBD | insider tables | `sig_insider` | Add |
| Institutional ownership | Not implemented | Sharadar / 13F source | TBD | institutional tables | `sig_institutional` | Add |
| Investor/holder data | Not implemented | Sharadar / reference source | TBD | investor/holder tables | `sig_institutional` | Add |
| Fund / ETF data | Not implemented or partial | Sharadar / Alpaca / other source | TBD | fund/ETF tables | `sig_sector_rotation`, `sig_macro` | Add |
| Agentic trade memory | Minimal/log based | PostgreSQL + pgvector | `data_agentic/` | `decision_memory`, `trade_outcomes` | typed agent tools | Add |
| Evidence embeddings | Not implemented | pgvector | TBD | vector columns / evidence tables | retrieval tools | Later |

Architecture components:

| Component | Role | Status |
|---|---|---|
| PostgreSQL | Main relational database for deterministic data, candidates, decisions, outcomes, and evals | Exists |
| pgvector | Vector search for similar setups, trade memory, and later text evidence | Add |
| Alpaca | Historical/paper market data and paper trading | Exists |
| Charles Schwab | Live brokerage/execution target | Partial |
| FRED | Macro data source | Exists |
| FMP | Current fundamentals source | Exists, temporary |
| Sharadar | Target replacement for FMP fundamentals plus future ownership, insider, institutional, reference, and possible OHLCV data | Add |
| Signal modules | Convert raw/processed data into prefilter-ready feature sets | Exists, needs naming cleanup |
| Prefilters | Deterministic candidate generators such as `pre_RS` | Exists, needs registry |
| Agent tools | Typed access to trade memory, backtests, portfolio context, current signal context, and evidence | Add |

Signal feed modules:

| Signal Module | Purpose | Likely Prefilters |
|---|---|---|
| `sig_technicals` | price, volume, momentum, trend, ATR, volatility, breakouts, pullbacks, and indicators | `pre_RS`, breakout, reversal |
| `sig_fundamentals` | quality, value, growth, margins, balance sheet, valuation, and earnings growth | quality-growth, value, growth |
| `sig_macro` | rates, credit spreads, VIX, inflation, unemployment, and macro regime | regime filters, risk adjustment |
| `sig_insider` | insider buys/sells and insider accumulation | insider accumulation |
| `sig_institutional` | institutional ownership, 13F-style flows, holders, and ownership quality | institutional accumulation, ownership quality |
| `sig_sector_rotation` | sector, industry, benchmark, fund, and ETF relative strength | sector rotation, relative strength |

Core database additions:

- `prefilter_profiles`: registry of active deterministic prefilters and their versions
- `screened_candidates`: passing candidate packets emitted by prefilters
- `decision_memory`: agent verdicts, tool calls, evidence IDs, and selected trade plans
- `trade_outcomes`: realized outcomes for accepted trades
- `eval_results`: stored evaluation runs and metrics

Point-in-time requirements:

- store both `period_end` and `filing_date` for fundamentals
- store source, vendor, load timestamp, and data version where practical
- prefilters only use data available as of `decision_date`
- agent memory only retrieves trades resolved before `decision_date`
- current signal context is treated as transient unless attached to a recorded decision

Phase 0 output:

- documented data-source map
- table/repository inventory
- list of missing raw-data modules
- signal module naming plan
- source migration note: FMP now, Sharadar later
- PostgreSQL + pgvector architecture target

### Phase 1 — First deterministic signal: `pre_RS`

Convert the existing relative-strength momentum logic into the first registered prefilter:

- `pre_RS`: relative-strength momentum prefilter

It should emit a candidate packet instead of a prose prompt payload.

The packet must include:

- symbol and decision date
- prefilter/profile ID
- setup score
- passed gates
- risk flags
- default stop, target, and timeline IDs
- allowed stop choices
- allowed target choices
- allowed timeline choices
- maximum position size
- maximum loss
- deterministic baseline expectation if available
- backtest/walk-forward stats if available

This phase should be testable without any LLM call.

### Phase 2 — Multi-prefilter runner and candidate storage

Build the runner that executes all active deterministic prefilters before the agent.

The runner should:

- load active prefilters from `prefilter_profiles`
- run every active prefilter
- persist each passing candidate to `screened_candidates`
- allow multiple candidate packets for the same symbol when multiple prefilters pass
- attach profile-level backtest/walk-forward stats
- reject candidates that fail hard gates before the agent sees them

The agent cannot create a candidate for a prefilter that did not pass.

### Phase 3 — Typed agent-data tools

Add the tool boundary the agent must use before making a decision.

Initial tools:

- `get_prefilter_performance`
- `search_similar_setups`
- `get_recent_trade_memory`
- `get_portfolio_context`
- `get_current_signal_context`
- `run_mini_backtest`
- `search_sec_evidence` as fixture/stub
- `get_recent_filing_events` as fixture/stub

The tools may be partly stubbed at first, but they must return schema-valid data and record enough
metadata for audit.

### Phase 4 — Agentic PM spine

Add the orchestration layer:

- candidate packet schema
- agent verdict schema
- typed tool definitions
- tool-calling loop
- agent prompt focused on selecting from passing candidate packets
- decision writer

The agent verdict must include:

- accept/reject decision
- selected candidate packet ID
- selected stop ID
- selected target ID
- selected timeline ID
- conviction tier
- profit likelihood
- confidence
- tools called
- evidence IDs
- rationale

The conviction tier controls position size and risk budget:

- `HIGH_CONVICTION`: full allowed size
- `CONVICTION`: reduced size
- `LOW_CONVICTION`: small size
- `REJECT`: no position

The verdict must be structured and written to `decision_memory`.

### Phase 5 — Deterministic risk validation and portfolio wiring

Wire portfolio management to consume only validated agent verdicts.

The portfolio manager should:

- accept only structured agent verdicts
- enforce deterministic maximum position size and maximum loss
- derive position size from conviction tier
- enforce stop/target/timeline IDs from the selected candidate packet
- reject invalid stops, targets, timelines, or packet IDs
- enforce portfolio exposure, sector exposure, liquidity, volatility, and concentration limits
- allow the risk layer to reject or reduce an agent-approved trade
- backfill final outcomes into `trade_outcomes` and `decision_memory`

Run this first in debug/no-order mode.

### Phase 6 — Retrieval, memory, and walk-forward stats

Make the typed tools useful behind the interface.

Implement:

- similar setup search over normalized deterministic feature vectors
- retrieval of resolved prior trades only
- prefilter-level backtest and walk-forward performance
- recent performance by profile and market regime
- point-in-time filters so future outcomes are never visible
- optional pgvector support for numeric vectors and later text evidence

The key rule:

```sql
WHERE resolution_date < decision_date
```

### Phase 7 — Eval harness

Build the harness that compares agent-managed trades against deterministic defaults.

Measure:

- win rate
- expectancy
- drawdown
- selected stop versus default stop by prefilter/profile
- selected target versus default target by prefilter/profile
- selected timeline versus default timeline by prefilter/profile
- conviction-adjusted sizing versus full default size
- pass decisions versus prefilter baseline
- prefilter selection when multiple packets exist for the same symbol
- calibration of `profit_likelihood`
- lift from using similar-trade memory and walk-forward stats

The eval result should be stored in `eval_results`.

### Phase 8 — Optional SEC/evidence expansion

Only after the decision loop and eval harness work, add real SEC ingestion if it is still useful.

Possible additions:

- `raw_data/sec_data.py`
- `database/filings_repository.py`
- `filings`
- `filing_chunks`
- `filing_events`
- text embeddings for evidence retrieval

The orchestration interface should not change when SEC moves from fixture to real ingestion.

## Key implementation targets

Modify:

- `agents/analysts/sa_RS.py`
- `agents/pm_agent.py`
- `agents/llm_client.py`
- `database/db_connection.py`
- `database/fundamentals_repository.py`

Create:

- `orchestration/`
- `retrieval/`
- `evals/`
- `database/decision_memory_repository.py`
- `database/profiles_repository.py`
- `database/eval_repository.py`

Optional later:

- `raw_data/sec_data.py`
- `database/filings_repository.py`

## Verification

Unit tests:

- prefilter emits schema-valid candidate packets
- stop, target, and timeline choices validate correctly
- agent verdict rejects IDs not present in the candidate packet
- agent verdict cannot loosen deterministic risk
- typed tools return schema-valid data

Integration tests:

- debug buy path creates candidate packet, agent verdict, and decision-memory row
- portfolio manager accepts valid choices and rejects invalid choices
- sell path enforces deterministic floor plus agent tighten-only behavior
- outcomes are written back for eval

Eval tests:

- historical replay compares agent choice to default choice
- profit likelihood calibration is computed
- retrieval never returns unresolved or future trades

## First milestone

The first milestone is not real-time trading and not SEC ingestion.

The first milestone is:

> Prefilter emits a candidate packet with a risk menu, agent selects stop/target/timeline/size within
> that menu, portfolio logic validates it, decision memory records it, and an outcome can be compared
> against deterministic defaults.
