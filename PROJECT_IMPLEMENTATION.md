# QuorumNexus — Project Implementation

Last reconciled with the repository: **2026-07-20**

## Purpose

QuorumNexus is being built as an auditable, point-in-time portfolio-management
pipeline:

1. deterministic data and signal services expose facts;
2. deterministic strategies turn those facts into candidate and exit packets;
3. a bounded portfolio-management agent chooses only from valid candidates;
4. deterministic risk validates sizing and portfolio constraints;
5. execution opens or closes positions; and
6. completed trades become searchable decision memory.

The repository currently implements the data foundation, six signal services, one
partially completed deterministic strategy, strategy profiles, and the completed-trade
repository. The orchestration, agent-tool loop, risk validator, position store, and
production execution path are not implemented.

This document describes what exists now and clearly separates it from planned work.

## Current implementation status

| Area | Status | Current reality |
|---|---|---|
| PostgreSQL market data | Implemented | Sharadar/FRED tables and repositories exist. |
| Initial and incremental loading | Implemented | Bulk load and daily update modules exist; operational runs still require credentials and monitoring. |
| Technical indicators | Implemented | Computed locally and stored in `indicators`. |
| Signal layer | Implemented | Six stateless DataFrame services with raw `get_signals()` methods and opt-in `attach_*()` transformations. |
| Deterministic strategies | Partial | Only `sector_leaders` remains active. Its eligibility and exits work, but final ranking and top-five-per-sector selection are TODO. |
| Strategy profiles | Implemented | One seeded profile: `sector_leaders`. |
| Candidate orchestration | Not implemented | There is no registry/runner that coordinates strategies and agent handoff. |
| Agentic PM | Not implemented | `pm_agent.py` contains commented legacy code; only a thin LLM client remains active. |
| Deterministic portfolio risk | Not implemented | Profile limits exist, but no portfolio-level validator applies them. |
| Open-position state | Not implemented | No `position.json` reader/writer or lifecycle exists. |
| Execution | Partial, not integrated | Alpaca market data and Schwab adapters exist; neither is connected to the new strategy pipeline. |
| Decision memory | Repository implemented | Schema and point-in-time retrieval functions exist; no live lifecycle writes to it yet. |
| Automated tests | Passing locally | 52 tests pass; Ruff and compilation pass as of this reconciliation. |

## Architecture

```text
Sharadar / FRED / live market APIs
                 |
                 v
        PostgreSQL repositories
                 |
                 v
     stateless DataFrame signal services
                 |
                 v
      deterministic strategy packets
                 |
        [not implemented yet]
                 v
 agent selection -> risk validation -> execution
                 |
                 v
 position state -> completed-trade decision memory
```

### Separation of responsibilities

The architectural boundary is:

- repositories retrieve and store database rows;
- signal services expose raw point-in-time rows and optional derived facts;
- strategies decide whether facts are desirable, risky, or disqualifying;
- the future agent chooses among strategy-approved candidates;
- deterministic risk owns hard portfolio and sizing constraints; and
- execution owns broker mutations.

Signal services must not contain strategy verdicts such as “buy,” “hostile regime,”
“heavy selling,” or “delisting risk.” They may calculate objective values such as an
event-code list, days since an event, percentile rank, or quarter-over-quarter change.
The consumer interprets those values.

## Repository layout

| Path | Responsibility |
|---|---|
| `data/sharadar_data.py` | Sharadar API access for incremental loads. |
| `data/macro_data.py` | FRED ingestion and point-in-time release alignment. |
| `data/indicators.py` | Local technical-indicator calculation. |
| `data/live_equity.py` | Alpaca historical/intraday market-data adapter. |
| `data/signals/` | Stateless signal DataFrame services. |
| `database/market/` | Market-data table creation, insert/upsert, and read repositories. |
| `database/operational/` | Strategy profiles and completed-trade decision memory. |
| `decision_layer/strategy/` | Active deterministic entry and exit logic. |
| `decision_layer/agentic_layer/` | Future bounded PM layer; currently mostly a placeholder. |
| `set_up/setup_db.py` | Database extensions and table creation. |
| `set_up/load_data.py` | Initial bulk Sharadar load, indicators, and macro load. |
| `set_up/daily_update.py` | Incremental market-data and indicator updates. |
| `schwab/` | Schwab authentication, market data, and trading adapter. |

Legacy momentum, value, quality, sector-rotation, screening-feature, and universe-cache
implementations have been removed. They are not active architecture and should not be
referenced as current strategy components.

## Data foundation

### Sources and tables

| Domain | Source | PostgreSQL table | Repository |
|---|---|---|---|
| Equity OHLCV | Sharadar SEP | `equity_prices` | `database/market/equity_repo.py` |
| Fund/ETF OHLCV | Sharadar SFP | `fund_prices` | `database/market/fund_repo.py` |
| Company metadata | Sharadar TICKERS | `tickers` | `database/market/tickers_repo.py` |
| Fundamentals | Sharadar SF1 | `fundamentals` | `database/market/fundamentals_repo.py` |
| Insider transactions | Sharadar SF2 | `insider_transactions` | `database/market/insider_repo.py` |
| Institutional holdings | Sharadar SF3 | `institutional_holdings` | `database/market/institutional_repo.py` |
| Corporate events | Sharadar EVENTS | `events` | `database/market/event_repo.py` |
| Technical indicators | Locally calculated | `indicators` | `database/market/indicators_repo.py` |
| Macro history | FRED | `macro` | `database/market/macro_repo.py` |

The initial history begins at `2016-01-01`. `set_up/load_data.py` bulk-exports
Sharadar tables, loads them into PostgreSQL, computes indicators for every ticker
with price history (including delisted names), and then loads macro history.

`set_up/daily_update.py` incrementally updates prices, indicators, fundamentals,
insider transactions, events, ticker metadata, institutional holdings, and macro data.

### Database setup

`set_up/setup_db.py` enables pgvector and creates:

- `equity_prices`
- `fund_prices`
- `indicators`
- `tickers`
- `fundamentals`
- `insider_transactions`
- `institutional_holdings`
- `events`
- `macro`
- `strategy_profiles`
- `decision_memory`

Running the module directly currently calls `drop_all()` before `create_all()`.
It is destructive and must not be treated as a routine migration command.

## Signal layer

### Contract

All concrete signal classes inherit from `data.signals.sig.Signals`.

Each service follows this interface:

```python
frame = SomeSignals.get_signals(..., signal_day)
frame = SomeSignals.attach_something(frame, ...)
```

Rules:

- `get_signals()` returns the default point-in-time rows from the relevant SQL
  repository with only light shape/date normalization.
- Derived features are opt-in `attach_*()` class methods.
- Attachments return a copy or a new DataFrame; callers choose which ones to use.
- Public domain methods are named `get_signals()` or `attach_*()`.
- Calculation helpers use protected `_method` names.
- Signal services hold no per-run instance state.
- There are no signal-layer `Model` or `Snapshot` wrapper classes.

`CandidateSnapshot` and `ExitSnapshot` still exist in the strategy module. Those are
strategy boundary packets, not signal wrappers, so they do not violate this contract.
They may eventually be renamed to `CandidatePacket` and `ExitPacket` for clarity.

### Shared helpers

`data/signals/sig.py` provides:

- safe division and growth;
- positive ratios;
- market-wide percentile ranks;
- within-sector percentile ranks; and
- ticker-sector attachment from the metadata repository.

Percentile methods produce values in `[0, 100]`. They are direction-free: a high
percentile only means a high raw value. The strategy decides whether high or low is
desirable.

### Signal services

| Service | Raw `get_signals()` output | Optional attachments |
|---|---|---|
| `TechnicalSignals` | Latest indicator row per ticker, indexed by ticker. | Market return percentiles; sector medians/ranks/relative returns; SPY or other benchmark excess returns. |
| `FundamentalSignals` | Latest available ART fundamental row per ticker, indexed by ticker. | Quarterly YoY growth; annual five-year history/change/volatility; calculated ratios; sector-relative metric percentiles. |
| `EventSignals` | Event rows inside the requested lookback window. | One row per requested ticker with earnings/13D recency and parsed recent event codes. |
| `InsiderSignals` | Filing-date-safe raw insider transactions with enough history to classify repeated purchases. | Purchase classification; ticker-level 30/90-day activity facts; market-cap normalization. |
| `InstitutionalSignals` | Raw holdings from conservatively available quarters. | Latest-quarter totals and quarter-over-quarter holder/value/unit changes. |
| `MacroSignals` | Point-in-time macro history through the signal date. | Calendar-lookback directional changes and claims statistics. |

Event, insider, and institutional source tables are one-to-many by ticker. Their raw
frames retain that grain, while their aggregate attachments deliberately return one
ticker-indexed row per requested ticker, including tickers with no matching source rows.

### Signal composition examples

Technical strategy facts:

```python
technicals = TechnicalSignals.get_signals(tickers, signal_day)
technicals = TechnicalSignals.attach_sectors(technicals)
technicals = TechnicalSignals.attach_return_percentiles(technicals)
technicals = TechnicalSignals.attach_sector_features(technicals, signal_day)
```

Fundamental research facts:

```python
fundamentals = FundamentalSignals.get_signals(tickers, signal_day)
fundamentals = FundamentalSignals.attach_sectors(fundamentals)
fundamentals = FundamentalSignals.attach_growth(fundamentals, signal_day)
fundamentals = FundamentalSignals.attach_history_features(
    fundamentals,
    signal_day,
)
fundamentals = FundamentalSignals.attach_ratios(fundamentals)
fundamentals = FundamentalSignals.attach_sector_ranks(fundamentals)
```

One-to-many event facts:

```python
event_rows = EventSignals.get_signals(tickers, signal_day)
event_facts = EventSignals.attach_event_facts(
    event_rows,
    tickers,
    signal_day,
)
```

## Point-in-time requirements

Every strategy and signal query must use only information available on or before its
`signal_day`.

Current protections include:

- latest indicator rows are constrained to `date <= signal_day`;
- the active universe requires a trade within ten calendar days of `signal_day`,
  preventing stale delisted “zombie” rows;
- fundamentals use `datekey <= signal_day`;
- insider transactions are filtered by `filingdate <= signal_day`;
- events are filtered by event date through `signal_day`;
- institutional holdings use a conservative 45-day post-quarter filing delay;
- release-sensitive macro series are aligned to first-release availability dates; and
- decision-memory retrieval requires `exit_date < decision_date`.

Known limitations:

1. `tickers` stores current sector labels rather than historically versioned labels.
   Historical sector-relative ranks can therefore contain classification look-ahead.
   Treat older sector backtests cautiously until sector history is sourced.
2. Institutional data lacks actual filing acceptance dates. The universal 45-day delay
   is conservative but approximate, so institutional facts remain research/evidence
   context rather than deterministic gates.
3. Sharadar revision/restatement storage semantics still need a targeted audit to prove
   that revised historical fundamentals cannot overwrite what was known earlier.
4. The event service defaults to a 20-day window. Its “days since” outputs therefore
   mean days since an event found within that window, not unbounded historical recency.

## Active deterministic strategy

### `sector_leaders`

`decision_layer/strategy/strat_sector_leaders.py` is the only active strategy.
It contains:

- `SLEntryScreener`
- `SLExitMonitor`
- `CandidateSnapshot`
- `ExitSnapshot`

The seeded `sector_leaders` profile currently specifies:

- maximum position: `5%`
- maximum loss: `10%`
- conviction multipliers:
  - `HIGH_CONVICTION`: `1.0`
  - `CONVICTION`: `0.6`
  - `LOW_CONVICTION`: `0.3`

These limits are stored but are not yet connected to a portfolio-level risk validator.

### Entry pipeline

The SQL prefilter requires:

- Sharadar SEP ticker;
- USD currency;
- NYSE or NASDAQ;
- domestic common stock;
- not a secondary share class;
- at least 15 valid observations among the latest 20 price rows;
- median 20-row dollar volume of at least `$5,000,000`;
- latest trade no more than ten calendar days before the signal date;
- latest point-in-time ART market cap of at least `$1,000,000,000`;
- positive common net income;
- positive 60-day return; and
- positive 252-day return.

The strategy then explicitly attaches technical sectors, return percentiles, and sector
features. It parses recent event facts and excludes:

| Event code | Strategy interpretation |
|---|---|
| `31` | delisting risk |
| `13` | bankruptcy |
| `42` | restatement |
| `36` | late filing |
| `26` | material impairment |

The final required price gates are:

- `close > sma_200`; and
- `trend_slope_60d * r_squared_60d > 0`.

Non-disqualifying context flags include overbought RSI, low liquidity, deep drawdown,
loose consolidation, high volatility, elevated ATR, recent earnings, and mega-cap
crowding.

### Current ranking gap

The intended result is each sector's strongest healthy trends, ultimately retaining the
top five per sector. That ranking is **not implemented**:

- every candidate currently receives `setup_score = 0.0`;
- the proposed trend-quality formula is still a TODO; and
- `SLEntryScreener.run()` returns all passing candidates rather than a top-five-per-sector
  menu.

This is the highest-priority deterministic implementation gap.

### Exit pipeline

`SLExitMonitor` applies rules in precedence order:

1. `MAXIMUM_LOSS_BREACH` when return from entry is at or below the profile's
   `max_loss_pct` (`-10%` for `sector_leaders`);
2. `THESIS_INVALIDATED` when drawdown from the stored high-water mark is at or below
   `-20%`; or
3. `THESIS_INVALIDATED` when price falls below the 200-day moving average.

If current indicator data is unavailable, the monitor holds rather than fabricating an
exit. `CONCERNING_EVENTS` remains an allowed decision-memory exit reason, but no active
agent watchlist currently produces it.

## Phase 2 — Candidate runner and decision memory

Phase 2 connects deterministic candidate packets to open-position state and, after
exit, completed-trade memory. The database contracts already exist; the runner and
position lifecycle do not.

### `strategy_profiles`

The table is a seeded, read-only registry during normal runs. It identifies a strategy
and supplies deterministic maximum position, maximum loss, and conviction-size
multipliers. Executable strategy selection remains code-owned.

Only `sector_leaders` is currently seeded.

#### Strategy-profile contract

| Key | `profile_id` | `name` | `description` |
|---|---|---|---|
| Explanation | Database identity for the seeded profile. | Unique code-owned strategy name; currently `sector_leaders`. | Human-readable description of the strategy and intended menu. |
| Consumer | Profile lookup and inspection. | Strategy lookup, `decision_memory`, position state, retrieval, and exit-policy lookup. | Agent context and operator inspection. |
| Datatype | `SERIAL PRIMARY KEY` | `VARCHAR(64) NOT NULL UNIQUE` | `TEXT` |

| Key | `max_position_pct` | `max_loss_pct` | `conviction_size_multipliers` |
|---|---|---|---|
| Explanation | Maximum portfolio allocation allowed for a position produced by the strategy. | Maximum loss allowed before `MAXIMUM_LOSS_BREACH` fires. | Maps each accepted conviction tier to a fraction of the strategy's maximum position size. |
| Consumer | Future deterministic position-sizing and portfolio-risk validator. | `SLExitMonitor`, future position state, and risk validator. | Future deterministic position-sizing validator. |
| Datatype | `NUMERIC(6,4) NOT NULL` | `NUMERIC(6,4) NOT NULL` | `JSONB NOT NULL` |

A profile row identifies and configures a strategy; it does not dynamically import or
execute Python code. Strategy registration remains explicit in the future orchestrator.

### `decision_memory`

`decision_memory` is designed for completed trades only. It stores:

- trade and strategy identity;
- the frozen candidate packet;
- agent conviction, rationale, evidence, and tool log;
- actual entry facts;
- actual exit facts and reason;
- detailed exit context; and
- a pgvector decision embedding.

Repository operations exist for inserting a completed trade, fetching a trade, fetching
prior trades, and similarity search.

#### Decision-memory contract

The following Markdown tables are column groups for one SQL table, not separate
subtables. Normal SQL columns hold stable trade facts, JSONB holds flexible candidate
and evidence payloads, and pgvector supports similar-completed-trade retrieval.

| Key | `trade_id` | `symbol` | `strategy_name` | `candidate_snapshot` |
|---|---|---|---|---|
| Explanation | UUID generated when the position opens and retained when the completed trade is inserted. | Traded stock. | Strategy that produced the candidate. | Frozen copy of everything the strategy presented to the agent. |
| Consumer | Position state, exit handoff, audit, and retrieval. | Position monitor and historical queries. | Strategy filtering and exit-rule lookup. | Thesis monitoring, audit, embedding generation, and future agent retrieval. |
| Datatype | `UUID PRIMARY KEY` | `VARCHAR(16) NOT NULL` | `VARCHAR(64) NOT NULL REFERENCES strategy_profiles(name)` | `JSONB NOT NULL` |

| Key | `conviction_tier` | `rationale` | `evidence` | `tool_call_log` |
|---|---|---|---|---|
| Explanation | Accepted trade's conviction tier, used for deterministic sizing. | Agent's concise reason for accepting the candidate. | Evidence references and summaries supporting the decision. | Tools used before acceptance and references to their results. |
| Consumer | Position-size audit and future agent context. | Historical retrieval and review. | Audit, embedding generation, and future agent retrieval. | Debugging and audit. |
| Datatype | `VARCHAR(24) NOT NULL` | `TEXT NOT NULL` | `JSONB` | `JSONB` |

| Key | `entry_date` | `entry_price` | `position_size_pct` |
|---|---|---|---|
| Explanation | Actual date the position opened. | Actual executed entry price. | Actual fraction of the portfolio allocated to the position. |
| Consumer | Holding-period and point-in-time calculations. | Maximum-loss monitoring and realized-return calculation. | Position and risk review. |
| Datatype | `DATE NOT NULL` | `NUMERIC(12,4) NOT NULL` | `NUMERIC(6,4) NOT NULL` |

| Key | `exit_date` | `exit_price` | `realized_pnl_pct` | `days_held` |
|---|---|---|---|---|
| Explanation | Date the position closed. | Actual executed exit price. | Final percentage return. | Number of days held. |
| Consumer | Point-in-time memory filtering. | Realized-return audit. | Future agent context and reporting. | Future agent context. |
| Datatype | `DATE NOT NULL` | `NUMERIC(12,4) NOT NULL` | `NUMERIC(10,6) NOT NULL` | `INT NOT NULL` |

| Key | `exit_reason` | `exit_context` | `decision_embedding` |
|---|---|---|---|
| Explanation | Coarse condition that caused the exit. | Specific rule, trigger values, and—when applicable—the agent's cited source. | Vector representation used for similar-completed-trade retrieval. |
| Consumer | Exit analysis and strategy reporting. | Exit debugging, audit, and future retrieval. | pgvector similarity search. |
| Datatype | `VARCHAR(32) NOT NULL` | `JSONB` | `VECTOR NOT NULL` |

Allowed conviction tiers are:

- `HIGH_CONVICTION`
- `CONVICTION`
- `LOW_CONVICTION`

Allowed exit reasons are:

- `MAXIMUM_LOSS_BREACH`
- `THESIS_INVALIDATED`
- `CONCERNING_EVENTS`

The SQL schema also enforces:

- `exit_date >= entry_date`;
- positive entry and exit prices;
- `0 < position_size_pct <= 1`; and
- non-negative `days_held`.

`exit_context` carries the specific rule inside the coarse `exit_reason`; a separate
`exit_policy` column is intentionally unnecessary. The future embedding must contain
entry-side context only—not realized outcomes—because a fresh candidate has no outcome
when it is used as a similarity query.

The schema correctly prevents future-outcome leakage during retrieval:

```sql
WHERE exit_date < :before_date
```

Current limitations:

- no position lifecycle writes completed trades yet;
- embedding generation is not implemented;
- embedding dimensionality has not been selected; and
- `decision_embedding` is required, so a lifecycle cannot insert until the embedding
  method is chosen or the schema is relaxed.

### Open positions

The intended store is a single-writer `position.json` managed by the future orchestrator
with atomic replacement. Neither the file nor its typed reader/writer currently exists.

#### Storage lifecycle contract

| Pipeline result | Storage action |
|---|---|
| Strategy candidate awaiting agent review | Keep only in the current run's memory. |
| Agent rejects candidate | Discard it. |
| Agent accepts but deterministic risk rejects it | Discard it. |
| Validated position opens | Generate `trade_id`; write the frozen candidate, agent context, limits, and execution facts to `position.json`. |
| Position exits | Add exit facts, `exit_reason`, `exit_context`, and embedding; insert one complete row into `decision_memory`; remove the position from `position.json`. |

## Agentic, risk, and execution layers

### Agentic layer

`decision_layer/agentic_layer/llm_client.py` is a thin Chat Completions wrapper for an
OpenAI model or local Ollama endpoint.

`pm_agent.py` is commented legacy code and is not an active implementation. There is no:

- candidate/verdict schema shared across layers;
- typed agent-data tool set;
- structured tool-calling loop;
- evidence audit trail;
- accepted-verdict handoff; or
- bounded PM orchestration.

### Deterministic risk

There is no active portfolio-level risk validator. The future validator must enforce:

- candidate identity and strategy profile;
- conviction tier;
- maximum position size;
- maximum loss;
- available capital;
- existing holdings and duplicate symbols;
- liquidity and volatility limits;
- sector concentration; and
- overall portfolio/correlation constraints.

The agent may reduce or reject risk. It must never increase limits or submit orders
directly.

### Execution

Existing pieces:

- Alpaca market-data adapter in `data/live_equity.py`;
- Schwab authentication and market/trading adapters under `schwab/`; and
- the `alpaca-py` dependency.

Missing:

- a validated order schema;
- a broker-neutral execution interface used by the new pipeline;
- fill reconciliation;
- open-position persistence;
- sell-side execution integration; and
- paper-trading end-to-end tests.

## Build order from the current state

### 1. Finish `sector_leaders`

- define the trend-quality ranking formula;
- rank within sector;
- keep the intended top five per sector;
- decide whether `CandidateSnapshot` should become `CandidatePacket`;
- attach the profile ID/limits and explicit entry-thesis facts needed downstream; and
- add focused entry and exit tests.

### 2. Build shared schemas and orchestration

- create typed candidate, agent-verdict, validated-order, position, and exit schemas;
- create a code-owned strategy registry;
- run exits before entries;
- resolve duplicate symbols and current holdings;
- hand the final candidate menu to the agent once; and
- keep rejected candidates transient.

### 3. Build deterministic risk validation

- validate candidate provenance;
- map conviction to a profile multiplier;
- enforce position, capital, sector, and portfolio constraints; and
- emit only bounded validated orders.

### 4. Build the position lifecycle

- implement the single-writer atomic `position.json` store;
- record frozen candidate and agent context at entry;
- maintain high-water marks;
- feed positions to `SLExitMonitor`; and
- close positions through the execution interface.

### 5. Build typed agent tools

Initial tools should provide:

- prior completed trades;
- similar completed trades;
- current portfolio exposure;
- current candidate/signal context;
- institutional research context; and
- recent event context.

Every tool result used in a decision must be auditable.

### 6. Complete decision memory

- choose one embedding model and fixed vector dimension;
- generate embeddings from entry-side context only;
- insert one complete record after each exit; and
- verify retrieval never exposes outcomes unavailable at the decision date.

### 7. Integrate paper execution

- choose the initial broker adapter;
- implement buy/sell order submission behind the shared execution interface;
- reconcile actual fills;
- update position state atomically; and
- run a fully isolated debug/paper path before enabling live mutations.

## Verification

Current local checks:

```bash
PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/ruff check data/signals decision_layer/strategy tests
.venv/bin/python -m compileall -q data/signals decision_layer/strategy set_up database
```

As of 2026-07-20:

- `52 passed`;
- Ruff passed;
- compilation and imports passed; and
- read-only PostgreSQL smoke tests passed for all six signal services.

The only observed test warning is a third-party `websockets.legacy` deprecation warning.

Required future integration tests:

- entry screening produces correctly ranked and bounded candidate packets;
- the agent cannot invent a candidate or loosen a deterministic limit;
- risk validation rejects malformed or over-limit verdicts;
- a validated paper order creates atomic open-position state;
- exit monitoring produces the correct precedence and context;
- an exited position becomes exactly one complete decision-memory row; and
- retrieval never returns a trade whose exit was unknown at the requested date.

## First milestone

The first meaningful milestone is:

> `sector_leaders` produces a correctly ranked candidate menu; a bounded structured
> agent accepts or rejects candidates; deterministic risk validates position size and
> portfolio constraints; paper execution records open positions atomically; exit rules
> close them; and each completed trade becomes one searchable, point-in-time-safe row in
> `decision_memory`.

Real-time trading, multiple strategy families, broad news ingestion, and formal factor
evaluation are outside this first milestone.
