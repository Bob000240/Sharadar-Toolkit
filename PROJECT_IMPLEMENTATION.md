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

All active deterministic strategies run before the agent.

The deterministic suite consists of:

- `strat_momentum`
- `strat_value`
- `strat_quality`
- `strat_smartmoney`
- `strat_reversal`

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
| Phase 1 | Deterministic | In progress | `strat_momentum`, `strat_value`, `strat_quality`, and `strat_informed_activity` screens, entry modes, and exit policies are defined. `strat_reversal` remains to be specified. |
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
| `sig_technicals` | price, volume, momentum, trend, ATR, volatility, breakouts, pullbacks, and indicators | `strat_momentum`, `strat_reversal` |
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

Define all five strategies explicitly before implementing their candidate packets. A stock must pass
the strategy's screen and at least one of its entry modes; it does not need to pass every entry mode.

| Strategy | Universe | Best macro regime | Key flaws | Signal files | Screen | Entry modes |
|---|---|---|---|---|---|---|
| `strat_momentum` | Primarily liquid mid-cap and established small-cap US equities; qualifying large caps remain eligible; exclude nano, micro, and illiquid securities | Preferred, not required: persistent broad trends; broad market and sector participation; benign credit and liquidity; stable or falling volatility. Avoid high-volatility rebounds following broad market declines. Cycle labels are context, not gates | Momentum crashes during sharp regime reversals; whipsaw in range-bound markets; high turnover and trading costs; crowded or overextended leaders; sector concentration; negatively skewed crash risk | `sig_technicals`<br>`sig_sector_rotation`<br>`sig_macro` | Sector leadership; liquid stock in a primary uptrend; positive volatility-adjusted momentum; at least two positive return horizons; benchmark or sector relative strength; no hard volatility, liquidity, drawdown, or structural risk failure.<br><br>**Qualifying large caps:** top-quartile momentum; positive 20-, 60-, and preferably 252-day returns; benchmark and sector outperformance; price above the 50-day and 200-day averages with the 50-day above the 200-day; strong trend quality; sector leadership; acceptable volatility and extension; and at least one valid entry mode | **Momentum reacceleration:** renewed momentum after consolidation<br>**52-week-high breakout:** prior 52-week high breaks with volume, bullish MA structure, and acceptable extension<br>**Pullback reclaim:** controlled 2-10% pullback with trend intact, followed by a 20-day or 50-day support/reclaim trigger<br><br>A candidate may qualify for more than one mode. |
| `strat_value` | Liquid small-, mid-, and large-cap US common stocks; exclude nano, micro, and illiquid securities. Financials and REITs are excluded only in v1 until dedicated sector metrics exist | Preferred, not required: broadening recovery or early expansion; improving growth and credit; rising inflation expectations; wide value-growth valuation dispersion. Interest rates and curve slope are context, not gates | Value traps and distress; peak-cycle earnings creating false cheapness; sector concentration; accounting and intangible-asset bias; long convergence and prolonged underperformance; specialized sectors require dedicated metrics | `sig_fundamentals`<br>`sig_technicals`<br>`sig_events`<br>`sig_sector_rotation`<br>`sig_macro` | Rank valuation within sector rather than against the full market. Require at least two valid valuation measures from earnings yield, FCF yield, EBITDA yield, book yield, and sales yield as a fallback; require the composite to rank in the cheapest 30% of its sector. Require positive operating cash flow and an acceptable aggregate financial-health score. Reject severe interest-coverage risk, extreme sector-relative leverage, or combined deterioration in revenue, margins, and cash flow. Negative or missing denominators cannot count as cheap. Macro is context and exposure guidance, not a normal company-level pass condition. | **Scheduled rank admission:** enter an eligible top-ranked candidate at a monthly or quarterly rebalance; this is the pure deterministic value baseline.<br>**Fundamental inflection:** after a newly available filing, require improvement in at least two operating, profitability, cash-flow, leverage, or liquidity measures while the stock remains cheap and financially viable.<br>**Confirmed repricing:** require benchmark or sector outperformance plus a recent EMA cross or key moving-average reclaim without overbought extension; a positive post-earnings reaction with increased volume strengthens the setup.<br><br>Filing-driven and close-confirmed setups become eligible on the next trading session. A candidate may qualify for more than one mode. |
| `strat_quality` | Primarily liquid mid- and large-cap US common stocks; established small caps remain eligible with complete multi-year fundamentals and sufficient liquidity. Exclude financials and REITs in v1 until dedicated quality metrics exist | Preferred, not required: slowing growth; tightening credit; elevated uncertainty or volatility; late-cycle/risk-off conditions. Quality remains eligible across regimes but may lag early-cycle speculative or low-quality rallies | Can become expensive or crowded; may lag high-beta and low-quality rallies; sector concentration and overlap with growth/low-volatility factors; ROE can be inflated by leverage or buybacks; backward-looking profitability may deteriorate; accounting and sector differences can create false quality signals | `sig_fundamentals`<br>`sig_technicals`<br>`sig_macro` | Require sufficient liquidity and approximately five years of point-in-time fundamentals. Rank within sector on four transparent pillars: current profitability and cash conversion; five-year profitability growth; balance-sheet and operating stability; and capital discipline through payout, dilution, and leverage direction. Require the composite in the sector's top 30%, profitability at or above the 60th percentile, safety at or above the 30th percentile, positive operating cash flow, and no hard distress. At least the profitability, growth, and safety pillars must be valid; capital discipline may be missing without inventing a neutral score. Use technical volatility as separate risk evidence, not inside the accounting composite. Valuation is context and a crowding warning, not a quality gate. | **Scheduled rank admission:** enter a newly eligible, top-ranked candidate at a monthly or quarterly rebalance; this is the pure deterministic quality baseline.<br>**Filing-driven quality upgrade:** after a newly available filing, require admission into the top 30% plus improvement in at least two quality pillars, positive operating cash flow, and no hard distress; enter on the next trading session.<br>**Controlled pullback reclaim:** while quality eligibility remains intact, require a controlled pullback toward the 20-day or 50-day average without breaking the primary trend, followed by a support reclaim with stable benchmark or sector relative strength.<br><br>A positive post-filing price reaction may strengthen the upgrade setup but is not treated as an earnings-surprise signal without analyst-estimate data. Filing-driven and close-confirmed setups become eligible on the next trading session. A candidate may qualify for more than one mode. |
| `strat_informed_activity` | Liquid small-, mid-, and large-cap US common stocks across sectors; emphasize established small and mid caps, where informative insider activity may be more consequential, while excluding nano, micro, and illiquid securities. Apply stricter liquidity and position-size limits to smaller companies | No single preferred macro regime: company-specific information is primary. Insider buying may be most useful during broad fear or stock-specific dislocations, while 13D activism is event-driven across regimes. Severe market-liquidity or credit stress should reduce exposure and position size rather than serve as a normal company-level gate | Signals are sparse and episodic; routine or compensation-related insider transactions are not informative; insider sales have many non-informational motives; reporting delays and rapid repricing can leave little edge; raw purchase value is size-biased; small-cap results are vulnerable to spreads and market impact; passive 13G filings do not imply activism; the current EVENTS schema cannot distinguish an initial 13D from an amendment; 13D events can become crowded or already priced; insiders and activists can still be wrong | `sig_insider`<br>`sig_events`<br>`sig_fundamentals`<br>`sig_technicals`<br>`sig_macro` | Apply a shared gate: eligible liquid common stock; all evidence available by `decision_date`; no bankruptcy, delisting, restatement, or other hard event failure; and no combined cash burn, extreme leverage, and inadequate liquidity. Do not require an uptrend or favorable macro regime.<br><br>Then require at least one independent evidence lane:<br>**Opportunistic insider accumulation:** open-market/private purchase code `P` filed within 30 days; classify recurring same-month purchases after three prior years as routine; require either at least two distinct opportunistic buyers including an officer or director, or one materially large opportunistic purchase after normalization by market cap, size bucket, and change in the buyer's post-transaction holdings. Insider sales are warnings rather than automatic vetoes.<br>**Activist 13D:** a fresh Schedule 13D-coded event, provisionally within seven calendar days. Passive 13G filings do not qualify. Because the current EVENTS schema lacks filing identity and amendment status, the 13D lane must carry an unresolved-amendment flag and cannot authorize automatic entry until the source is enriched or the filing is verified. | **Opportunistic cluster disclosure:** enter after a newly filed purchase creates a qualifying cluster of at least two distinct opportunistic buyers, including an officer or director, within the 30-day evidence window; enter on the next trading session after the qualifying filing.<br>**Material senior-insider purchase:** enter after a newly filed opportunistic officer or director purchase independently clears the approved materiality threshold using market-cap/size-bucket rank and the purchase fraction of post-transaction holdings; enter on the next trading session.<br>**Verified activist 13D:** enter after a fresh initial Schedule 13D is verified and the shared safety gate passes. If the disclosure response remains within the approved extension limit, enter on the next trading session; otherwise wait for a controlled consolidation or pullback reclaim while the event remains eligible.<br><br>Use filing availability, not the earlier transaction date, and never fill at the filing-day close. Generic breakouts are not required. The 13D mode remains non-automatic until initial-versus-amended status can be verified. A candidate may qualify for more than one mode. |

##### Universal exit policies

| Universal exit policy | Applies to | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|---|
| Protective stop | All open positions | Price reaches the maximum approved loss or the initial structure stop | Live | Broker or deterministic risk monitor | Exit |
| Strategy invalidation | All open positions | The strategy thesis or entry structure becomes false | Strategy-specific: intraday, daily, or event-driven | Deterministic position monitor | Exit or reduce according to the approved policy |
| Macro defense | Portfolio and new entries | Macro overlay becomes hostile or enters a high-volatility rebound regime | Daily and after material releases | Deterministic risk layer | Block new entries, reduce exposure, or tighten risk; do not force a healthy position exit by itself |
| Judgment review | Ambiguous deterioration | Evidence weakens without crossing a deterministic exit threshold | Daily or event-driven | Agent | Hold, reduce, or exit within the allowed policy |

##### Momentum exit policies

| Momentum exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Reacceleration invalidation | Price closes below the consolidation low that defined the setup | Daily after close | Deterministic position monitor | Exit |
| Breakout invalidation | Price fails the breakout and closes back below the approved pivot or base | Daily after close | Deterministic position monitor | Exit |
| Pullback-reclaim invalidation | Price closes below the pullback swing low or loses the reclaimed support level | Daily after close | Deterministic position monitor | Exit |
| Trend and relative-strength failure | A confirmed close below the approved trend average occurs with deteriorating momentum or benchmark/sector relative strength | Daily after close | Deterministic position monitor | Exit |
| No-follow-through time stop | The expected momentum move fails to develop within the approved initial window, provisionally 10-20 trading sessions | Daily | Deterministic position monitor | Exit |
| Trailing winner protection | A profitable position breaches its approved ATR, price-structure, or moving-average trail | Live or daily, as encoded | Broker or deterministic risk monitor | Exit the protected remainder |
| Momentum-crash defense | A high-volatility market rebound follows a broad decline and the position also shows adverse trend or relative-strength evidence | Daily and event-driven | Deterministic risk layer | Reduce exposure or tighten risk; macro conditions alone do not force the exit |

Momentum does not use a fixed take-profit for the entire position; optional partial realization may
be followed by a deterministic trail so large winners are not truncated.

##### Value exit policies

| Value exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Valuation convergence | The sector-relative value composite falls below the exit band, initially the 50th percentile after entry at or above the 70th percentile | Monthly or quarterly rebalance | Deterministic position monitor | Exit and reallocate; do not use an arbitrary fixed profit target |
| Fundamental thesis failure | Operating cash flow turns negative, the financial-health score falls below its floor, or severe interest-coverage, leverage, liquidity, or combined-deterioration flags appear | After each newly available filing | Deterministic position monitor | Exit on the next trading session for hard failures; reduce or review isolated soft deterioration |
| Fundamental-inflection failure | The operating or financial improvements that justified entry reverse in a later filing while the discount remains unresolved | After each newly available filing | Deterministic position monitor | Exit on the next trading session |
| Confirmed-repricing failure | Price loses the approved reclaim level and benchmark or sector relative strength also deteriorates | Daily after close | Deterministic position monitor | Exit or reduce according to the approved structure policy |
| Stale thesis | After an initial 12-month review horizon, neither valuation convergence nor measurable fundamental improvement has occurred and stronger eligible value candidates exist | Monthly review after the horizon | Portfolio construction | Exit and reallocate |

The entry and exit valuation bands intentionally use hysteresis to avoid turnover around one cutoff.
Pure scheduled-rank and fundamental-inflection entries retain the universal maximum-loss protection
but do not receive a tight chart-based stop by default. Confirmed-repricing entries may use their
reclaim structure as an additional stop.

Exact percentile bands, ATR multipliers, confirmation periods, and time-review horizons remain
walk-forward parameters.

##### Quality exit policies

| Quality exit policy | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|
| Hard quality-thesis failure | Operating cash flow turns negative, a hard-distress flag appears, or newly available evidence shows severe profitability, solvency, or accounting-quality failure | After each newly available filing or material event | Deterministic position monitor | Exit on the next trading session |
| Buffered quality-rank exit | The sector-relative quality composite falls below the exit band, initially the 50th percentile after entry at or above the 70th percentile | Monthly or quarterly rebalance | Deterministic position monitor | Exit and reallocate; an incumbent between the entry and exit bands may remain to limit turnover |
| Confirmed multi-pillar deterioration | At least two core pillars materially deteriorate across newly available filings, without yet meeting a hard-failure condition | After each newly available filing | Deterministic position monitor and agent | Reduce or place under review; exit if deterioration persists or the rank exit band is crossed |
| Filing-upgrade invalidation | The pillar improvements that justified a filing-driven entry reverse in a later filing, and the candidate no longer satisfies the upgrade thesis | After each newly available filing | Deterministic position monitor | Exit on the next trading session |
| Pullback-reclaim invalidation | A pullback-reclaim entry closes below its approved swing low or loses the primary trend while benchmark or sector relative strength also deteriorates | Daily after close | Deterministic position monitor | Exit according to the approved structure policy |
| Quality replacement | An incumbent is inside the retention buffer, portfolio capacity is constrained, and a materially stronger eligible quality candidate is available | Monthly or quarterly rebalance | Portfolio construction | Replace the weaker holding without treating the rotation as a thesis failure |

Quality does not use a fixed take-profit or a short no-follow-through time stop. Valuation expansion,
macro deterioration, one soft filing, or loss of a moving average does not by itself invalidate a
scheduled-rank quality holding. Those conditions may block additions, reduce sizing, or prompt agent
review, but an exit requires the universal risk policy, quality-rank decay, corroborated fundamental
deterioration, or invalidation of an entry-specific price structure.

The entry and exit quality bands intentionally use hysteresis. Exact rank bands, definitions of
material pillar deterioration, rebalance frequency, and technical confirmation periods remain
walk-forward parameters.

##### Informed-activity exit policies

| Informed-activity exit policy | Applies to | Trigger | Cadence | Owner | Action |
|---|---|---|---|---|---|
| Hard company-thesis failure | All informed-activity positions | Bankruptcy, delisting, restatement, material impairment, severe financing stress, or newly available fundamentals showing that the shared safety gate has decisively failed | After each filing or material event | Deterministic position monitor | Exit on the next trading session |
| Insider-thesis reversal | Insider-purchase entries | A qualifying buyer materially reverses the purchase, or broad insider selling appears together with corroborating fundamental deterioration. Ordinary or isolated insider sales do not qualify because sales have many non-informational motives | After each newly available insider filing | Deterministic position monitor | Exit for a same-buyer material reversal; reduce or review broader selling only when corroborated |
| Insider-evidence expiry | Insider-purchase entries | At the initial six-month review, the position has produced neither meaningful fundamental or relative-price improvement nor renewed qualifying opportunistic buying | Monthly review beginning after six months | Portfolio construction and agent | Exit or replace with stronger evidence; renewed qualifying activity may start a new evidence window |
| Stale insider thesis | Insider-purchase entries | Twelve months have elapsed without renewed qualifying activity or measurable thesis progress | Monthly review after twelve months | Portfolio construction | Exit; do not convert an expired information signal into an indefinite discretionary holding |
| Activist campaign failure or withdrawal | Verified 13D entries | A later filing reports abandonment, a failed campaign, conversion to passive intent, or reduction below the reporting threshold for reasons inconsistent with successful thesis resolution | Event-driven | Deterministic position monitor | Exit on the next trading session |
| Activist catalyst resolution | Verified 13D entries | The campaign reaches a completed acquisition, tender, asset sale, settlement, governance change, or other terminal outcome that resolves the original catalyst | Event-driven | Deterministic position monitor and portfolio construction | Exit at the encoded event/settlement policy or reassess under another strategy; do not retain the position under an expired activist label |
| Delayed-entry structure failure | 13D entries that waited for consolidation or pullback | Price closes below the approved post-disclosure base or pullback low with deteriorating benchmark or sector relative strength | Daily after close | Deterministic position monitor | Exit according to the approved structure policy |

Informed activity does not use a fixed profit target. Insider-purchase evidence is reviewed over a
medium horizon because the documented return response can persist for several months; activist
campaigns may require substantially longer and therefore do not receive the insider lane's automatic
six- or twelve-month expiry. Universal protective stops still apply to both lanes.

The current EVENTS schema cannot observe 13D amendment identity, stake reduction, passive
conversion, or campaign resolution. Automated activist entry and exit policies therefore remain
disabled until that source is enriched or a verified filing-retrieval path supplies those facts.
Owner-linked insider reversal monitoring also requires retaining buyer identity in the position
thesis rather than relying only on aggregate sell counts.

Exact review horizons, material-sale thresholds, corroboration requirements, and event-resolution
rules remain walk-forward parameters.

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
- `database/operational/strategy_profiles_repository.py`
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
- candidate/verdict schemas, preferably shared by strategies, tools, risk, and evals

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
