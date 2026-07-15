# QuorumNexus — Build Strategy

## Goal

Build a small, auditable paper-trading loop around deterministic strategies and a bounded agent.

The project succeeds when all three strategies can produce ranked candidates, the agent can select
from those candidates, deterministic risk checks can validate an entry, open positions can be
monitored against deterministic exit rules, and every completed trade becomes searchable decision
memory. A formal evaluation harness is outside the current scope.

## Governance

AI coding sessions on this repository follow `docs/AI_EXECUTION_HANDBOOK.md` (evidence authority,
decision records, layer-boundary rules, quality gates, self-review protocol). Current project state
lives in `docs/WorkStatus.md`; point-in-time and architecture invariants live in
`docs/invariants.md`. This document is the top of the evidence authority order — it changes only by
deliberate edit, and schema/strategy/data-ownership changes require a Decision Record
(`docs/decisions/`) before code.

## Chosen Architecture

QuorumNexus follows a professional portfolio-management separation of duties:

- signal/research models find opportunities
- portfolio construction decides sizing and allocation
- risk systems enforce hard limits
- execution systems place orders
- the agent acts like a bounded PM/trader inside the mandate

The agent can express conviction, but deterministic systems enforce the risk mandate.

### Deterministic Signal Layer

All active deterministic strategies run before the agent.

The deterministic suite consists of:

- `strat_momentum`
- `strat_value`
- `strat_quality`

Each passing strategy emits a candidate packet with:

- symbol and decision date
- strategy/profile ID
- setup score
- passed gates
- risk flags
- entry thesis and the facts needed to test whether it remains valid
- maximum position size
- maximum loss
- point-in-time signal context

The agent cannot create a candidate for a strategy that did not pass.

### Agentic PM Layer

The agent receives candidate packets from all passing strategies.

Before making a decision, the agent must use typed tools to fetch agentic evidence, such as:

- similar completed trades
- recent trade memory
- current portfolio exposure
- current signal and market context
- optional event/news/evidence context

The agent decides:

- whether to accept or reject the trade
- which strategy-generated candidate packet to use when multiple packets exist
- conviction tier
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
- no trade unless a deterministic strategy passed
- no uncontrolled orders

The risk layer may reject or reduce an agent-approved trade.

### Execution Layer

The execution layer only receives validated orders. It places trades and stores current open-position
state in `positions.json`. The position monitor applies the universal maximum-loss rule and the
strategy-specific thesis-invalidation rule.

### Database and Memory Layer

Candidates remain in memory while the agent evaluates them. Rejected candidates and candidates
blocked by deterministic risk validation are discarded. When a validated position opens, its frozen
candidate packet, agent context, and execution state are stored in `positions.json`.

When that position exits, one complete append-only row is inserted into PostgreSQL
`decision_memory`. JSONB stores the flexible candidate and evidence payloads; pgvector makes completed
trades searchable by similarity. There is no separate screened-candidate, outcome, or eval table.

## Build order

### Current progress

Phase 0 is mostly complete. The project now has the data-source map, Sharadar-backed raw data access,
market repositories, signal modules, PostgreSQL table setup, pgvector enablement, strategy profiles,
and a completed-trade decision-memory repository.

The remaining Phase 0 work is cleanup rather than architecture discovery:

- verify initial database loads end-to-end for the full tradeable universe
- confirm point-in-time fields are consistently used by each signal and repository
- add any missing indexes needed by the first strategy and retrieval path
- keep `.env`, vendor keys, broker tokens, and local data artifacts out of git
- align doc names with the current `data/`, `database/`, and `decision_layer/` layout

| Phase | Layer | Progress | Notes |
|---|---|---|---|
| Phase 0 | Foundation | Mostly complete | Data access, repositories, setup, signals, strategy profiles, and completed-trade memory exist. |
| Phase 1 | Deterministic | In progress | `strat_momentum`, `strat_value`, and `strat_quality` screens and entry modes are defined; exit policy details have been reset to class skeletons before implementation. |
| Phase 2 | Deterministic | Partial | The profile registry and decision-memory schema exist; the runner, accepted-verdict handoff, `positions.json`, and exit-to-memory flow still need to be built. |
| Phase 3 | Agentic | Not started | Typed agent-data tools need schemas, implementations, and audit logging. |
| Phase 4 | Agentic | Partial | PM and LLM modules exist; structured tool-calling agent verdict loop still needs to be built. |
| Phase 5 | Agentic | Partial | Point-in-time completed-trade queries exist; embedding generation and useful retrieval tools remain. |

### Phase 0 — Data foundation and architecture inventory

Define the deterministic data foundation the strategies will use. This phase maps what exists, what
will be added, which source owns each dataset, where it is stored, and which signal modules feed the
strategies.

| Domain | Current Source | Future/Target Source | Current Code | Storage | Feed Medium | Status |
|---|---|---|---|---|---|---|
| Equity OHLCV | Sharadar SEP / Alpaca live snapshot | Sharadar primary; Schwab/Alpaca as needed for live context | `data/sharadar_data.py`, `data/live_equity.py` | `equity_prices` via `database/market/equity_repo.py` | `sig_technicals` | Implemented; verify full-history load |
| Fundamentals | Sharadar SF1 | Sharadar | `data/sharadar_data.py` | `fundamentals` via `database/market/fundamentals_repo.py` | `sig_fundamentals` | Implemented; keep point-in-time checks tight |
| Company descriptors | Sharadar TICKERS | Sharadar/reference source | `data/sharadar_data.py` | `tickers` via `database/market/tickers_repo.py` | `sig_fundamentals`, `sig_sector_rotation` | Implemented |
| Macro | FRED / ALFRED vintages | FRED / ALFRED vintages | `data/macro_data.py` | `macro` via `database/market/macro_repo.py` | `sig_macro` | Implemented with first-release alignment, source freshness dates, and directional regime features |
| Technical indicators | Internal calculation | Internal calculation | `data/indicators.py` | `indicators` via `database/market/indicators_repo.py` | `sig_technicals` | Implemented |
| Insider transactions | Sharadar SF2 | Sharadar | `data/sharadar_data.py` | `insider_transactions` via `database/market/insider_repo.py` | `sig_insider` | Implemented; validate signal thresholds |
| Institutional ownership | Sharadar SF3 | Sharadar / 13F source | `data/sharadar_data.py` | `institutional_holdings` via `database/market/institutional_repo.py` | optional typed agent evidence | Implemented; excluded from deterministic strategy gates |
| Investor/holder data | Sharadar SF3-derived holdings | Sharadar/reference source | `data/sharadar_data.py` | `institutional_holdings` | `sig_institutional` | Implemented as holdings-level data |
| Fund / ETF data | Sharadar SFP | Sharadar / Alpaca / other source | `data/sharadar_data.py` | `fund_prices` via `database/market/fund_repo.py` | `sig_sector_rotation`, `sig_macro` | Implemented |
| Events | Sharadar EVENTS | Sharadar / event source if later needed | `data/sharadar_data.py` | `events` via `database/market/event_repo.py` | `sig_events`, evidence stubs | Implemented |
| Agentic trade memory | PostgreSQL + pgvector | PostgreSQL + pgvector | `database/operational/decision_memory_repository.py` | `decision_memory` | typed agent tools | Completed-trade schema and queries implemented; tools next |
| Evidence embeddings | Not implemented | pgvector | TBD | vector columns / evidence tables | retrieval tools | Later |

Architecture components:

| Component | Role | Status |
|---|---|---|
| PostgreSQL | Main relational database for deterministic market data, strategy profiles, and completed-trade memory | Implemented |
| pgvector | Vector search over completed trades and later text evidence | Enabled in setup; embedding method still needs selection |
| Alpaca | Historical/paper market data and paper trading | Exists |
| Charles Schwab | Live brokerage/execution target | Partial |
| FRED | Macro data source | Exists |
| FMP | Former fundamentals source | Superseded by Sharadar in current code path |
| Sharadar | Primary source for fundamentals, ownership, insider, institutional, reference, events, fund prices, and OHLCV | Implemented |
| Signal modules | Convert raw/processed data into strategy-ready feature sets | Implemented under `data/signals/` |
| Strategies | Deterministic candidate generators such as `strat_momentum` | Base classes and profile registry implemented under legacy names; naming migration and first production packet are next |
| Agent tools | Typed access to completed-trade memory, portfolio context, current signal context, and evidence | Next major build item |

Signal feed modules:

| Signal Module | Purpose | Likely Strategies |
|---|---|---|
| `sig_technicals` | price, volume, momentum, trend, ATR, volatility, breakouts, pullbacks, and indicators | `strat_momentum` |
| `sig_fundamentals` | quality, value, growth, margins, balance sheet, valuation, and earnings growth | quality-growth, value, growth |
| `sig_macro` | point-in-time rates, credit, VIX, inflation, and labor levels plus directional changes and an explainable regime overlay | regime filters, risk adjustment |
| `sig_insider` | insider buys/sells and insider accumulation | insider accumulation |
| `sig_institutional` | factual, stale-dated institutional ownership summaries with no score or interpreted flags | optional typed agent evidence only |
| `sig_sector_rotation` | sector, industry, benchmark, fund, and ETF relative strength | sector rotation, relative strength |

Core operational storage:

- `strategy_profiles`: seeded, read-only registry containing each strategy's position and loss limits
- `positions.json`: current validated open positions; to be implemented
- `decision_memory`: append-only completed trades, including the frozen candidate, agent context,
  execution facts, outcome, exit cause, and retrieval embedding

Passing candidates are intentionally not persisted. Rejected and risk-blocked candidates are also not
retained.

Point-in-time requirements:

- store both `period_end` and `filing_date` for fundamentals
- store source, vendor, load timestamp, and data version where practical
- align release-sensitive macro observations to their first known release date rather than their
  economic observation date
- strategies only use data available as of `decision_date`
- agent memory only retrieves trades resolved before `decision_date`
- current signal context is treated as transient unless attached to a recorded decision

Known point-in-time biases (open):

These are look-ahead leaks currently accepted with mitigation. Each breaks strict
point-in-time correctness until the data model is extended.

- **Current-state sector labels — highest impact.** `tickers` is a flat current snapshot
  (one sector per name, no history: 21,896 rows = 21,896 tickers), so `sig_fundamentals`
  ranks a company's *entire* history under its *present* sector. Because value and quality
  gate on sector-relative percentiles, this is a look-ahead leak in their core mechanism.
  Measured magnitude: low-single-digit % of names on average, but **systematic and
  concentrated**, not random noise. The largest contributor is the 2018-19 recomposition of
  "Communication Services" (Google/Meta/Netflix/Disney leaving Technology / Consumer
  Cyclical) — 297 currently-Comm-Services names have fundamentals predating the change, and
  the affected names skew mega-cap and highly liquid, so they dominate what the screens
  surface. The ART history (2016→2026) straddles the event. A direct count of all historical
  reclassifications is impossible from this DB — there is no temporal sector data at all,
  which is the root problem. **Mitigation until versioned sector data exists: restrict
  walk-forward calibration to ~2020-onward, where current labels are approximately valid,
  and treat any pre-2019 value/quality backtest number as sector-biased.**
- **Institutional 45-day filing delay** (`sig_institutional`). Actual 13F filing dates are
  absent, so a universal 45-day-after-quarter-end offset is assumed; holder identity,
  amendments, splits, and manager coverage can distort quarter-over-quarter changes.
  Contained because institutional data was removed from all deterministic gates (optional
  agent evidence only) — it influences no trade decision today. Quarantine stands until
  precise filing dates are sourced; do not wire it back into a gate before then.
- **Revised filings — secondary.** Fundamentals are filtered on `datekey <= decision_date`,
  correct *if* Sharadar rows are as-first-reported. If a restatement overwrote an earlier
  period rather than appending a row, revised numbers could leak. Needs a spot-check of
  Sharadar's revision-storage semantics, not assumed either way.

Phase 0 output:

- documented data-source map: mostly complete
- table/repository inventory: complete for current database shape
- list of missing raw-data modules: none required for the core decision loop
- signal module naming plan: complete around `sig_technicals`, `sig_fundamentals`, `sig_macro`,
  `sig_insider`, `sig_institutional`, `sig_sector_rotation`, and `sig_events`
- source migration note: FMP has been replaced by Sharadar for the current implementation path
- PostgreSQL + pgvector architecture target: implemented in setup, with retrieval usefulness still ahead

### Deterministic layer

The deterministic layer owns signal generation, candidate eligibility, candidate persistence, and
final risk validation. It is the hard boundary around the agent: the agent can choose among valid
options, but it cannot create candidates, expand the menu, increase risk, or send orders directly.

#### Phase 1 — Deterministic strategy suite

Define all three strategies explicitly before implementing their candidate packets. A stock must pass
the strategy's screen and at least one of its entry modes; it does not need to pass every entry mode.

| Strategy | Universe | Best macro regime | Key flaws | Signal files | Screen | Entry modes |
|---|---|---|---|---|---|---|
| `strat_momentum` | Primarily liquid mid-cap and established small-cap US equities; qualifying large caps remain eligible; exclude nano, micro, and illiquid securities | Preferred, not required: persistent broad trends; broad market and sector participation; benign credit and liquidity; stable or falling volatility. Avoid high-volatility rebounds following broad market declines. Cycle labels are context, not gates | Momentum crashes during sharp regime reversals; whipsaw in range-bound markets; high turnover and trading costs; crowded or overextended leaders; sector concentration; negatively skewed crash risk | `sig_technicals`<br>`sig_sector_rotation`<br>`sig_events` | **Momentum.** Screen = general momentum eligibility (all required):<br>• **Liquid** (dollar volume ≥ $5M).<br>• **Primary uptrend** (price > 200-day).<br>• **Trend confirmed** (slope × R² > 0).<br>The momentum *thesis* lives in the two entry modes, which key off different things and admit different names. Leading-sector tilt boosts the score (Moskowitz & Grinblatt 1999). | Two research-distinct entries; at least one required (they admit different names):<br>**Trend continuation** (Jegadeesh & Titman 1993): top-quintile 12-month momentum (`return_252d_percentile ≥ 80`) with intermediate corroboration (`return_60d_percentile ≥ 70`) — **skipping the recent month** (`return_20d`), whose ≤1-month component reverses (Novy-Marx 2012) — above the 50-day with broad multi-horizon strength. *[rank — cited; bands CALIBRATION]*<br>**52-week-high breakout** (George & Hwang 2004): a *confirmed* breakout — a fresh 52-week high (below→above transition, not proximity) on a volume surge with bullish MA structure; need not be top-quintile on trailing returns.<br><br>A candidate may qualify for both. |
| `strat_value` | Liquid small-, mid-, and large-cap US common stocks; exclude nano, micro, and illiquid securities. Financials and REITs are excluded only in v1 until dedicated sector metrics exist | Preferred, not required: broadening recovery or early expansion; improving growth and credit; rising inflation expectations; wide value-growth valuation dispersion. Interest rates and curve slope are context, not gates | Value traps and distress; peak-cycle earnings creating false cheapness; sector concentration; accounting and intangible-asset bias; long convergence and prolonged underperformance; specialized sectors require dedicated metrics | `sig_fundamentals`<br>`sig_events` | **Value = sector-relative cheapness + Piotroski trap filter.** Cheapness is the sector-ranked value composite — earnings yield (E/P; Basu 1977), FCF yield, EV/EBITDA yield (Loughran & Wellman 2011), book yield (B/M; Fama & French 1992), sales yield — computed point-in-time in `sig_fundamentals`. All gates required:<br>• **Cheapest 30% in sector** (`value_composite_percentile ≥ 70`) with ≥2 valid yield measures; negative/missing denominators cannot count as cheap. *[rank — cited]*<br>• **Operating cash flow > 0** — not a distress trap (Piotroski 2000). *[sign — cited]*<br>• **Low accruals: CFO > net income** (`accrual_quality > 0`) — earnings backed by cash (Sloan 1996). *[sign — cited]*<br>• **Reject** broad deterioration, or cash burn under leverage. Macro is a base-layer overlay, not a company-level gate. | **Scheduled rank admission (single entry gate):** a passing name is admitted at the next monthly/quarterly rebalance. Value is a periodic cross-sectional rank sort, so one deterministic entry — no fundamental-inflection mode (the Piotroski health signal now lives in the screen) and no confirmed-repricing mode (a value+momentum timing overlay is optional and not yet enabled). |
| `strat_quality` | Liquid mid- and large-cap US common stocks in v1; small caps are deferred until a dollar-volume liquidity floor and a fundamental-completeness gate exist (the blanket mid/large cut stands in for them for now). Exclude financials and REITs in v1 until dedicated quality metrics exist | Preferred, not required: slowing growth; tightening credit; elevated uncertainty or volatility; late-cycle/risk-off conditions. Quality remains eligible across regimes but may lag early-cycle speculative or low-quality rallies | Can become expensive or crowded; may lag high-beta and low-quality rallies; sector concentration and overlap with growth/low-volatility factors; ROE can be inflated by leverage or buybacks; backward-looking profitability may deteriorate; accounting and sector differences can create false quality signals | `sig_fundamentals`<br>`sig_events` | **Quality = Quality-Minus-Junk composite** (Asness, Frazzini & Pedersen 2019): a point-in-time, sector-ranked blend of four pillars — profitability, growth, safety, payout — computed in `sig_fundamentals`. All gates required:<br>• **QMJ composite in sector top 30%** (`quality_composite_percentile ≥ 70`), with ≥3 of 4 pillars scorable; profitability pillar led by gross profits/assets (Novy-Marx 2013). *[rank — cited]*<br>• **Operating cash flow > 0** — earnings are real (Piotroski 2000). *[sign — cited]*<br>• **Low accruals: CFO > net income** (`accrual_quality > 0`) — earnings backed by cash (Sloan 1996). *[sign — cited]*<br>• **Not extreme leverage** (de ≤ 2). *[level — CALIBRATION, walk-forward]*<br>Valuation is crowding context, not a gate. Macro is applied as a portfolio overlay by the base layer, not a company-level gate. | **Scheduled rank admission (single entry gate):** a passing name is admitted at the next monthly/quarterly rebalance. QMJ is a periodic cross-sectional rank sort with no market-timing overlay, so quality has exactly one deterministic entry. No filing-upgrade mode (the improvement signal already lives in the QMJ growth pillar) and no pullback-reclaim mode (a technical timing overlay has no research basis for a quality factor). |

##### Exit policy skeleton

The deterministic exit system has two conditions:

| Condition | Policy | Behavior |
|---|---|---|
| Maximum-loss breach | `UniversalExitPolicy` | Exit when any position reaches its approved maximum loss. This applies to every strategy and cannot be overridden by the agent. |
| Entry-thesis invalidation | `StrategyExitPolicy` | Exit when the evidence that justified entry is no longer true. Each strategy defines its own invalidation rules. |

`UniversalExitPolicy` and the `StrategyExitPolicy` base live in
`decision_layer/det_layer/strategy.py`. `MomentumExitPolicy`, `ValueExitPolicy`, and
`QualityExitPolicy` live beside their respective strategies.

The open-position monitor evaluates both policies. No triggered decision means hold; either condition
can trigger an exit, with the universal maximum-loss rule taking precedence. Strategy-specific rules
must mirror the entry thesis and remain deterministic. Define their exact inputs and triggers when the
position context and thesis state are implemented.

#### Phase 2 — Candidate runner and decision memory

Build the deterministic runner that executes all registered strategies, ranks their passing results,
and sends only the top five candidates from each strategy to the agent. With three strategies, the
agent receives at most fifteen candidate packets per run. Candidate packets remain in memory while the
agent evaluates them; they are not written to SQL.

##### Strategy-profile contract

The strategy-profile table is seeded during database setup and read-only during normal strategy runs.
It identifies the strategy and supplies its deterministic position and loss limits.

| Key | `profile_id` | `name` | `description` | `max_position_pct` | `max_loss_pct` | `conviction_size_multipliers` |
|---|---|---|---|---|---|---|
| Explanation | Database-generated strategy identity. | Unique strategy name, such as `momentum`. | Human-readable explanation of the strategy. | Maximum portfolio allocation allowed for a position produced by the strategy. | Maximum loss allowed before `UniversalExitPolicy` exits the position. | Converts an agent conviction tier into a fraction of the maximum position size. |
| Consumer | `decision_memory`, `positions.json`, and historical retrieval. | Strategy registry, exit-policy lookup, agent context, and logs. | Agent context and inspection. | Candidate snapshot and deterministic position-sizing validator. | Candidate snapshot and `UniversalExitPolicy`. | Deterministic position-sizing validator. |
| Datatype | `SERIAL PRIMARY KEY` | `VARCHAR(64) NOT NULL UNIQUE` | `TEXT` | `NUMERIC(6,4) NOT NULL` | `NUMERIC(6,4) NOT NULL` | `JSONB NOT NULL` |

Executable strategy selection remains code-owned: `StratMomentum`, `StratValue`, and `StratQuality`
all run before the agent receives the completed candidate set. A profile row identifies a strategy; it
does not dynamically load or execute Python code.

##### Decision-memory contract

`decision_memory` contains only completed trades that were accepted, passed risk validation, opened,
and later exited. It does not store agent rejections, risk rejections, or open positions. Each row is
inserted once after exit and is not gradually updated through a trade lifecycle.

The three Markdown tables below are column groups for one SQL table, not separate subtables. Normal
SQL columns hold stable trade facts, JSONB holds flexible candidate and evidence payloads, and pgvector
supports similar-completed-trade retrieval.

| Key | `trade_id` | `symbol` | `decision_date` | `profile_id` | `candidate_snapshot` |
|---|---|---|---|---|---|
| Explanation | UUID generated when the position opens and retained when the completed trade is inserted. | Traded stock. | Date the agent selected the candidate. | Strategy that produced the candidate. | Frozen copy of everything the strategy presented to the agent. |
| Consumer | `positions.json`, exit handoff, audit, and retrieval. | Position monitor and historical queries. | Point-in-time retrieval and audit. | Strategy filtering and exit-policy lookup. | Thesis monitoring, audit, embedding generation, and future agent retrieval. |
| Datatype | `UUID PRIMARY KEY` | `VARCHAR(16) NOT NULL` | `DATE NOT NULL` | `INT NOT NULL REFERENCES strategy_profiles(profile_id)` | `JSONB NOT NULL` |

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

| Key | `exit_date` | `exit_price` | `realized_pnl_pct` | `days_held` | `exit_reason` | `exit_policy` | `decision_embedding` |
|---|---|---|---|---|---|---|---|
| Explanation | Date the position closed. | Actual executed exit price. | Final percentage return. | Number of days held. | Deterministic condition that caused the exit. | Policy class that produced the exit decision. | Vector representation of the completed trade. |
| Consumer | Point-in-time memory filtering. | Realized-return audit. | Future agent context and reporting. | Future agent context. | Audit and future agent context. | Exit debugging and strategy analysis. | Similar-trade retrieval through pgvector. |
| Datatype | `DATE NOT NULL` | `NUMERIC(12,4) NOT NULL` | `NUMERIC(10,6) NOT NULL` | `INT NOT NULL` | `VARCHAR(32) NOT NULL` | `VARCHAR(64) NOT NULL` | `VECTOR NOT NULL` |

Allowed conviction tiers are `HIGH_CONVICTION`, `CONVICTION`, and `LOW_CONVICTION`. Exit reasons are
`MAXIMUM_LOSS_BREACH` and `THESIS_INVALIDATED`. `decision_embedding` remains dimensionless until one
embedding method is selected; after that, its dimension must be fixed consistently.

##### Storage lifecycle

| Pipeline result | Storage action |
|---|---|
| Strategy candidate awaiting agent review | Keep only in the current run's memory. |
| Agent rejects candidate | Discard it. |
| Agent accepts but deterministic risk rejects it | Discard it. |
| Validated position opens | Generate `trade_id` and write the frozen candidate, agent context, risk limits, and execution facts to `positions.json`. |
| Position exits | Add the exit facts and embedding, insert one complete row into `decision_memory`, then remove the position from `positions.json`. |

The runner should:

- run every strategy in the code-owned strategy registry
- resolve the shared tradeable universe once
- rank each strategy's passing results before agent handoff
- keep only the top five packets from each strategy
- validate each packet's strategy identity, risk limits, entry theses, and point-in-time context
- send the completed in-memory candidate set to the agent once
- pass only accepted verdicts to deterministic risk validation
- write validated open positions to `positions.json`
- insert one complete `decision_memory` row only after a position exits
- allow the same symbol to produce separate decisions when multiple strategies pass

The agent cannot create a candidate, ask to run another strategy after seeing the set, or change the
deterministic packet. `trade_id` is the durable identity shared by the open-position JSON record and
the completed SQL row.

##### Accepted-verdict handoff

Before opening an agent-approved position:

- confirm the verdict references a current in-memory candidate packet
- validate the conviction tier
- calculate position size from the strategy profile's conviction multiplier
- enforce `max_position_pct`, `max_loss_pct`, and available portfolio capacity
- write the executed position to `positions.json`

Rejected or invalid verdicts are discarded. Exit monitoring belongs to `UniversalExitPolicy` and the
selected strategy's `StrategyExitPolicy`. After exit, insert the completed trade into
`decision_memory` and remove it from `positions.json`.

### Agentic layer

The agentic layer interprets the deterministic candidate set, asks for typed evidence, and either
accepts or rejects each opportunity. It cannot create candidates, loosen risk, or execute orders.

#### Phase 3 — Typed agent-data tools

Add the tool boundary the agent must use before making a decision.

Initial tools:

- `search_similar_trades`
- `get_recent_trade_memory`
- `get_portfolio_context`
- `get_current_signal_context`
- `get_institutional_summary`
- `search_evidence_fixture` as fixture/stub if text evidence is needed later
- `get_recent_event_context` as fixture/stub

The tools may be partly stubbed at first, but they must return schema-valid data and record enough
metadata for audit.

#### Phase 4 — Agentic PM spine

Add the orchestration layer:

- candidate packet schema
- agent verdict schema
- typed tool definitions
- tool-calling loop
- agent prompt focused on selecting from passing candidate packets
- handoff to deterministic verdict validation

The agent verdict must include:

- accept/reject decision
- selected in-memory candidate reference
- conviction tier
- tools called
- evidence IDs
- rationale

The conviction tier controls position size and risk budget:

- `HIGH_CONVICTION`: full allowed size
- `CONVICTION`: reduced size
- `LOW_CONVICTION`: small size
- `REJECT`: no position

The verdict must be structured. Rejected verdicts are discarded; accepted verdicts are retained in
`positions.json` only if deterministic validation and execution succeed.

#### Phase 5 — Completed-trade retrieval

Make the typed tools useful behind the interface.

Implement:

- one consistent embedding method for completed trades
- similar-trade search over `decision_embedding`
- recent completed-trade retrieval, optionally filtered by strategy profile
- point-in-time filters so future outcomes are never visible
- optional later support for separately indexed text evidence

The key rule:

```sql
WHERE exit_date < decision_date
```

## Key implementation targets

Modify:

- `decision_layer/det_layer/strat_momentum.py`
- `decision_layer/det_layer/strategy.py`
- `decision_layer/agentic_layer/pm_agent.py`
- `decision_layer/agentic_layer/llm_client.py`
- `database/db_connection.py`
- `database/market/fundamentals_repo.py`
- `database/operational/strategy_profiles_repository.py`
- `database/operational/decision_memory_repository.py`

Create:

- `decision_layer/orchestration/`
- `retrieval/`
- `positions.json` and a small typed position-state reader/writer
- typed tool modules for agent evidence access
- risk validation module for agent verdicts
- `decision_layer/schemas/` — shared candidate-packet and verdict schemas used by strategies, tools,
  and risk (TASK-001 in `docs/tasks/`)

## Verification

Unit tests:

- strategy emits schema-valid candidate packets
- each strategy ranks before handing off at most five packets
- agent verdict cannot loosen deterministic risk
- typed tools return schema-valid data
- exit policies return deterministic hold/exit decisions

Integration tests:

- debug buy path creates a candidate packet, a validated agent verdict, and an open-position JSON entry
- portfolio manager accepts valid choices and rejects invalid choices
- sell path enforces maximum loss and strategy-thesis invalidation
- exit handoff inserts one complete trade into `decision_memory` and removes it from `positions.json`
- retrieval never returns a trade whose exit was not known by the requested decision date

## First milestone

The first milestone is not real-time trading and not broad text-evidence ingestion.

The first milestone is:

> Strategy suite produces at most fifteen ranked candidates, the agent accepts or rejects them,
> deterministic risk validates position size and limits, `positions.json` tracks open positions, and
> every exited position becomes one complete searchable row in `decision_memory`.
