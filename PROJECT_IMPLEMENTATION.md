# QuorumNexus — Build Strategy

## Goal

Build the deterministic spine first, then make the agent useful inside strict risk boundaries.

The project succeeds when QuorumNexus can prove whether an evidence-aware agent improves trade
management over deterministic defaults. The target is not an unconstrained trading oracle. The target
is an auditable system where every agent choice can be compared against the default stop, target,
timeline, and pass/enter decision.

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
- default stop loss
- default target price
- default holding timeline
- allowed stop choices
- allowed target choices
- allowed timeline choices
- maximum position size
- maximum loss
- relevant backtest/walk-forward stats

The agent cannot create a candidate for a strategy that did not pass.

### Agentic PM Layer

The agent receives candidate packets from all passing strategies.

Before making a decision, the agent must use typed tools to fetch agentic evidence, such as:

- strategy backtest and walk-forward performance
- similar past trades
- recent trade memory
- current portfolio exposure
- current signal and market context
- mini-backtest results
- optional event/news/evidence context

The agent decides:

- whether to accept or reject the trade
- which strategy-generated candidate packet to use when multiple packets exist
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
- no trade unless a deterministic strategy passed
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
- agent accept/reject decisions versus strategy baseline
- calibration of profit likelihood

## Build order

### Current progress

Phase 0 is mostly complete. The project now has the data-source map, Sharadar-backed raw data access,
market repositories, signal modules, PostgreSQL table setup, pgvector enablement, operational
candidate tables, decision memory, trade outcomes, and eval-result storage in place.

The remaining Phase 0 work is cleanup rather than architecture discovery:

- verify initial database loads end-to-end for the full tradeable universe
- confirm point-in-time fields are consistently used by each signal and repository
- add any missing indexes needed by the first strategy and retrieval path
- keep `.env`, vendor keys, broker tokens, and local data artifacts out of git
- align doc names with the current `data/`, `database/`, and `decision_layer/` layout

| Phase | Layer | Progress | Notes |
|---|---|---|---|
| Phase 0 | Foundation | Mostly complete | Data access, repositories, setup, signals, candidate storage, decision memory, outcomes, and eval storage exist. |
| Phase 1 | Deterministic | In progress | `strat_momentum`, `strat_value`, and `strat_quality` screens, entry modes, and exit policies are defined and research-backed; these three make up the complete deterministic suite. |
| Phase 2 | Deterministic | Partial | The profile registry and `screened_candidates` exist; the active-strategy runner and pre-agent gates still need to be built. |
| Phase 3 | Deterministic | Partial | Execution/PM code exists; deterministic verdict validation and no-order debug path need tightening. |
| Phase 4 | Agentic | Not started | Typed agent-data tools need schemas, implementations, and audit logging. |
| Phase 5 | Agentic | Partial | PM and LLM modules exist; structured tool-calling agent verdict loop still needs to be built. |
| Phase 6 | Agentic | Partial | Point-in-time memory queries exist; useful retrieval, mini-backtests, and walk-forward stats remain. |
| Phase 7 | Agentic | Partial | `eval_results` storage exists; replay/evaluation harness remains. |

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
| Agentic trade memory | PostgreSQL + pgvector | PostgreSQL + pgvector | `database/agent_memory/decision_memory_repository.py` | `decision_memory`, `trade_outcomes` | typed agent tools | Schema implemented; tools next |
| Evidence embeddings | Not implemented | pgvector | TBD | vector columns / evidence tables | retrieval tools | Later |

Architecture components:

| Component | Role | Status |
|---|---|---|
| PostgreSQL | Main relational database for deterministic data, candidates, decisions, outcomes, and evals | Implemented |
| pgvector | Vector search for similar setups, trade memory, and later text evidence | Enabled in setup; vector indexes supported |
| Alpaca | Historical/paper market data and paper trading | Exists |
| Charles Schwab | Live brokerage/execution target | Partial |
| FRED | Macro data source | Exists |
| FMP | Former fundamentals source | Superseded by Sharadar in current code path |
| Sharadar | Primary source for fundamentals, ownership, insider, institutional, reference, events, fund prices, and OHLCV | Implemented |
| Signal modules | Convert raw/processed data into strategy-ready feature sets | Implemented under `data/signals/` |
| Strategies | Deterministic candidate generators such as `strat_momentum` | Base classes and profile registry implemented under legacy names; naming migration and first production packet are next |
| Agent tools | Typed access to trade memory, backtests, portfolio context, current signal context, and evidence | Next major build item |

Signal feed modules:

| Signal Module | Purpose | Likely Strategies |
|---|---|---|
| `sig_technicals` | price, volume, momentum, trend, ATR, volatility, breakouts, pullbacks, and indicators | `strat_momentum` |
| `sig_fundamentals` | quality, value, growth, margins, balance sheet, valuation, and earnings growth | quality-growth, value, growth |
| `sig_macro` | point-in-time rates, credit, VIX, inflation, and labor levels plus directional changes and an explainable regime overlay | regime filters, risk adjustment |
| `sig_insider` | insider buys/sells and insider accumulation | insider accumulation |
| `sig_institutional` | factual, stale-dated institutional ownership summaries with no score or interpreted flags | optional typed agent evidence only |
| `sig_sector_rotation` | sector, industry, benchmark, fund, and ETF relative strength | sector rotation, relative strength |

Core database additions:

- strategy profiles: implemented registry of active deterministic strategies and their versions; persistence naming still needs migration
- `screened_candidates`: implemented storage for passing candidate packets emitted by strategies
- `decision_memory`: implemented storage for agent verdicts, tool calls, evidence IDs, and selected trade plans
- `trade_outcomes`: implemented storage for realized outcomes for accepted trades
- `eval_results`: implemented storage for evaluation runs and metrics

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

##### Universal exit policies

| Universal exit policy | Applies to | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|---|
| Protective stop | All open positions | Price reaches the maximum approved loss or the initial structure stop | Live | Broker or deterministic risk monitor | Exit |
| Strategy invalidation | All open positions | The strategy thesis or entry structure becomes false | Strategy-specific: intraday, daily, or event-driven | Deterministic position monitor | Exit or reduce according to the approved policy |
| Macro defense | Portfolio and new entries | Macro overlay becomes hostile or enters a high-volatility rebound regime | Daily and after material releases | Deterministic risk layer | Block new entries, reduce exposure, or tighten risk; do not force a healthy position exit by itself |
| Judgment review | Ambiguous deterioration | Evidence weakens without crossing a deterministic exit threshold | Daily or event-driven | Agent | Hold, reduce, or exit within the allowed policy |

> **A note on exits vs. entries.** The factor literature covers *entry and periodic
> rebalancing*, not discretionary exits, so exits are less citeable than the screens.
> Three honest categories appear below: **(a) rank decay** — symmetric with the entry
> rank sort, with hysteresis to limit turnover; **(b) hard-failure sign reversals** —
> the Piotroski/Sloan floors that gated entry turning false (cited); **(c) risk
> structure** — stops, trails, and time/review horizons, all `[CALIBRATION]`. Momentum
> is the exception with genuine exit research (Daniel & Moskowitz 2016, momentum
> crashes). No strategy uses a fixed take-profit.

##### Momentum exit policies

| Momentum exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Trend / relative-strength failure | Confirmed close below the trend average (e.g. 50-day) with momentum ranks rolling over — the Jegadeesh-Titman continuation is broken | Daily after close | Deterministic position monitor | Exit |
| 52-week-high breakout failure | A 52-week-high entry closes back below the breakout pivot or loses the 20-/50-day structure (mirrors the George-Hwang entry) | Daily after close | Deterministic position monitor | Exit |
| No-follow-through time stop | The move fails to develop within the formation-consistent window (Jegadeesh-Titman holding horizons; band `[CALIBRATION]`) | Daily | Deterministic position monitor | Exit |
| Momentum-crash defense | A high-volatility market rebound follows a broad decline and the position shows adverse trend/RS — the momentum-crash regime (Daniel & Moskowitz 2016) | Daily and event-driven | Deterministic risk layer | Reduce exposure or tighten risk; macro alone does not force the exit |
| Trailing winner protection | A profitable position breaches its approved ATR, price-structure, or moving-average trail | Live or daily, as encoded | Broker or deterministic risk monitor | Exit the protected remainder |

No fixed take-profit: momentum's edge lives in the positive-skew tail, so winners are trailed rather
than truncated (optional partial realization may precede the trail).

##### Value exit policies

| Value exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Valuation convergence (rank decay) | The sector value composite falls below the exit band (~50th pctile) after entry ≥70th — hysteresis to limit turnover | Monthly/quarterly rebalance | Deterministic position monitor | Exit and reallocate; no fixed profit target *(Fama-French mean reversion; bands `[CALIBRATION]`)* |
| Fundamental / trap failure | Operating cash flow turns negative, or accruals turn adverse (CFO < net income), or combined deterioration appears — the Piotroski/Sloan floor that gated entry is now false | After each new filing | Deterministic position monitor | Exit next session *(Piotroski 2000; Sloan 1996 — sign reversal)* |
| Stale thesis | After a ~12-month review, neither valuation convergence nor fundamental improvement has occurred and stronger eligible value names exist | Monthly review after the horizon | Portfolio construction | Exit and reallocate |

Entry and exit bands use hysteresis. A rank-sort entry keeps the universal maximum-loss stop but no
tight chart-based stop by default. Bands and review horizons remain `[CALIBRATION]`.

##### Quality exit policies

| Quality exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Quality-rank decay (buffered) | The QMJ composite falls below the exit band (~50th pctile) after entry ≥70th; an incumbent inside the buffer may stay to limit turnover | Monthly/quarterly rebalance | Deterministic position monitor | Exit and reallocate *(QMJ periodic rebalance; bands `[CALIBRATION]`)* |
| Hard quality-thesis failure | Operating cash flow turns negative, or accruals turn adverse (CFO < net income), or a hard-distress flag appears — the Piotroski/Sloan floor is now false | After each new filing or material event | Deterministic position monitor | Exit next session *(Piotroski 2000; Sloan 1996)* |
| Quality replacement | An incumbent is inside the retention buffer, capacity is constrained, and a materially stronger eligible quality name is available | Monthly/quarterly rebalance | Portfolio construction | Replace the weaker holding, not treated as a thesis failure |

No fixed take-profit and no short time stop — quality is a hold-and-compound factor. Valuation
expansion, macro deterioration, or one soft filing do not by themselves invalidate a holding; they may
block additions, reduce sizing, or prompt agent review. An exit requires the universal risk policy,
rank decay, or a hard-failure sign reversal. Bands remain `[CALIBRATION]`.

#### Phase 2 — Candidate runner, storage, and pre-agent gates

Build the deterministic runner that executes all active strategies and produces the only candidate
packets the agent is allowed to consider.

The runner should:

- load active strategies from the strategy profile registry
- resolve the eligible universe for each profile
- run every active strategy for the decision date
- normalize every passing result into the shared candidate-packet schema
- validate that each packet includes a complete risk menu before storage
- persist each passing candidate to `screened_candidates`
- allow multiple candidate packets for the same symbol when multiple strategies pass
- attach profile-level backtest/walk-forward stats
- reject candidates that fail hard gates before the agent sees them
- record enough rejection/audit metadata to debug why candidates did not pass

Candidate packets must include deterministic choices for:

- default and allowed stops
- default and allowed targets
- default and allowed timelines
- maximum position size
- maximum loss
- risk flags
- setup score
- point-in-time signal context
- backtest or walk-forward stats when available

The output of Phase 2 is a clean `screened_candidates` set for a decision date. The agent only
receives candidate IDs and packet contents that came from this table. It cannot create a candidate
for a strategy that did not pass, and it cannot ask to run a different strategy after seeing the
candidate set.

#### Phase 3 — Deterministic verdict validation and portfolio handoff

Validate every structured agent verdict against the selected candidate packet before portfolio or
execution code can act on it.

The validator should:

- accept only structured agent verdicts
- fetch the selected `screened_candidates` row by candidate ID
- reject verdicts that reference missing, stale, or mismatched candidate packets
- enforce that the selected stop, target, and timeline IDs exist in the candidate packet's menus
- reject any verdict that tries to loosen deterministic risk beyond the candidate envelope
- derive position size from conviction tier and profile size multipliers
- enforce maximum position size and maximum loss
- enforce portfolio exposure, sector exposure, liquidity, volatility, and concentration limits
- allow the risk layer to reject or reduce an agent-approved trade
- emit a validated order plan for debug/no-order mode first
- write validation status and final outcomes back into `trade_outcomes` and `decision_memory`

The risk layer is deterministic and cannot call the LLM. It is allowed to reduce, reject, or hold a
trade for manual/debug review, but it cannot expand the agent's chosen risk. Execution only receives
validated order plans.

### Agentic layer

The agentic layer interprets the deterministic candidate set, asks for typed evidence, selects from
allowed options, records its reasoning, and later helps evaluate whether those choices improved over
the deterministic defaults.

#### Phase 4 — Typed agent-data tools

Add the tool boundary the agent must use before making a decision.

Initial tools:

- `get_strategy_performance`
- `search_similar_setups`
- `get_recent_trade_memory`
- `get_portfolio_context`
- `get_current_signal_context`
- `get_institutional_summary`
- `run_mini_backtest`
- `search_evidence_fixture` as fixture/stub if text evidence is needed later
- `get_recent_event_context` as fixture/stub

The tools may be partly stubbed at first, but they must return schema-valid data and record enough
metadata for audit.

#### Phase 5 — Agentic PM spine

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

#### Phase 6 — Retrieval, memory, and walk-forward stats

Make the typed tools useful behind the interface.

Implement:

- similar setup search over normalized deterministic feature vectors
- retrieval of resolved prior trades only
- strategy-level backtest and walk-forward performance
- recent performance by profile and market regime
- point-in-time filters so future outcomes are never visible
- optional pgvector support for numeric vectors and later text evidence

The key rule:

```sql
WHERE resolution_date < decision_date
```

#### Phase 7 — Eval harness

Build the harness that compares agent-managed trades against deterministic defaults.

Measure:

- win rate
- expectancy
- drawdown
- selected stop versus default stop by strategy/profile
- selected target versus default target by strategy/profile
- selected timeline versus default timeline by strategy/profile
- conviction-adjusted sizing versus full default size
- pass decisions versus strategy baseline
- strategy selection when multiple packets exist for the same symbol
- calibration of `profit_likelihood`
- lift from using similar-trade memory and walk-forward stats

The eval result should be stored in `eval_results`.

## Key implementation targets

Modify:

- `decision_layer/det_layer/strat_momentum.py`
- `decision_layer/det_layer/strategy.py`
- `decision_layer/agentic_layer/pm_agent.py`
- `decision_layer/agentic_layer/llm_client.py`
- `database/db_connection.py`
- `database/market/fundamentals_repo.py`
- `database/operational/prefilter_profiles_repository.py` (planned rename: `strategy_profiles_repository.py`)
- `database/operational/screened_candidates_repository.py`
- `database/agent_memory/decision_memory_repository.py`
- `database/outcomes/trade_outcomes_repository.py`
- `database/outcomes/eval_repository.py`

Create:

- `decision_layer/orchestration/`
- `retrieval/`
- `evals/`
- typed tool modules for agent evidence access
- risk validation module for agent verdicts
- `decision_layer/schemas/` — shared candidate-packet and verdict schemas used by strategies, tools,
  risk, and evals (TASK-001 in `docs/tasks/`)

## Verification

Unit tests:

- strategy emits schema-valid candidate packets
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

The first milestone is not real-time trading and not broad text-evidence ingestion.

The first milestone is:

> Strategy emits a candidate packet with a risk menu, agent selects stop/target/timeline/size within
> that menu, portfolio logic validates it, decision memory records it, and an outcome can be compared
> against deterministic defaults.
