# QuorumNexus — Research Platform Implementation

Last reconciled with the repository: **2026-07-26**

## Purpose

QuorumNexus is an auditable, point-in-time equity research platform.

It helps a researcher:

1. define a reproducible universe, filter set, and ranking model;
2. discover and compare companies using information available on a chosen date;
3. inspect the evidence behind every score, inclusion, and exclusion;
4. replay the same research method historically;
5. save a falsifiable thesis and monitor changes to its evidence; and
6. learn from prior research without requiring an automated trade.

The platform supports investment decisions. It does not manage a portfolio or place
orders.

## Product boundary

### In scope

- Point-in-time market, fundamental, event, ownership, and macro data
- Declarative screens and ranking models
- Explainable candidate lists and company dossiers
- Saved and versioned research runs
- Historical replay and model evaluation
- Thesis notes, counterevidence, invalidation conditions, and research journals
- Evidence-change alerts
- An optional AI research assistant grounded in platform facts

### Out of scope

- Brokerage, custody, and order execution
- Automated portfolio management
- Position sizing and capital allocation
- Broker reconciliation and fill handling
- Stop-loss or automated exit execution
- A trading agent that accepts candidates and submits orders
- Open-position state and completed-trade memory

Alpaca may remain a market-data provider. It is not part of an execution path.

## Current implementation status

| Area | Status | Current reality |
|---|---|---|
| PostgreSQL market data | Implemented | Sharadar and FRED tables and repositories exist. |
| Initial and incremental loading | Implemented | Bulk load and daily update modules exist; operational use requires credentials and monitoring. |
| Technical features | Implemented | Features are calculated locally and stored in `technical_features`. |
| Point-in-time signal services | Implemented | Six stateless services expose technical, fundamental, event, insider, institutional, and macro facts. |
| Generic field catalog | Branch work | `platform-pipeline` contains a declarative field registry intended to drive validation, ranking, and future UI controls. |
| Generic filtering and ranking | Branch work | `platform-pipeline` contains parameterized filter, ranker, and screen orchestration modules. |
| `sector_leaders` | Experimental | It exercises screening and ranking but has no reliable saved evidence of predictive value. It is a preset, not the architecture. |
| Historical evaluation | Not active | The previous harness is deleted in the current worktree and must be replaced with an adjusted-return, experiment-oriented evaluator. |
| Saved research runs | Not implemented | Screen results and their specifications are not persisted. |
| Company dossiers | Not implemented | Facts exist, but there is no unified research-facing dossier contract. |
| Thesis and journal storage | Not implemented | No research thesis lifecycle exists. |
| API and user interface | Not implemented | The project is currently a Python/CLI research engine. |
| Alerts | Not implemented | Evidence changes are not persisted or compared between runs. |
| Automated tests | Passing | 52 tests pass locally; one third-party deprecation warning remains. |

## Target architecture

```text
Sharadar / FRED / market-data APIs
                 |
                 v
        PostgreSQL source repositories
                 |
                 v
     point-in-time signal and feature services
                 |
                 v
        field catalog + ScreenSpec
                 |
                 v
      filter -> rank -> explain -> persist
                 |
        +--------+---------+
        |                  |
        v                  v
 company dossier     historical evaluator
        |                  |
        +--------+---------+
                 |
                 v
      thesis / journal / evidence alerts
                 |
                 v
             API and UI
```

### Separation of responsibilities

- Source repositories retrieve and store vendor or calculated rows.
- Signal services expose objective, point-in-time facts and derived measurements.
- The field catalog describes which facts can be filtered or ranked, their units,
  canonical direction where one exists, coverage limits, and research definitions.
- A `ScreenSpec` is the complete serializable description of a research screen.
- The screen engine assembles facts, applies filters, ranks candidates, and explains
  attrition.
- Research persistence freezes the specification, data cutoff, candidates, scores,
  evidence, and model version for each run.
- The evaluator replays saved specifications and measures them against explicit
  baselines.
- Dossiers organize evidence around one company without manufacturing a verdict.
- Theses store the researcher's claims, counterevidence, catalysts, and invalidation
  conditions.
- The API and UI expose the same contracts used by replay and tests.
- An AI assistant may summarize, compare, and challenge evidence, but it must cite
  platform facts and may not silently alter a screen or score.

Signal services must not contain verdicts such as `buy`, `sell`, `hostile regime`, or
`heavy selling`. They may calculate objective values such as event codes, days since an
event, percentile ranks, or quarter-over-quarter changes. A saved screen or researcher
decides how those facts should be interpreted.

## Repository layout

| Path | Responsibility |
|---|---|
| `data/sharadar_data.py` | Sharadar API access for incremental loads. |
| `data/macro_data.py` | FRED ingestion and release-aware macro alignment. |
| `data/technical_features.py` | OHLCV-derived technical feature calculation. |
| `data/live_equity.py` | Alpaca market-data adapter. |
| `data/signals/` | Stateless point-in-time signal and feature services. |
| `database/source/` | Source table creation, ingestion, and read repositories. |
| `database/state/` | Temporary home of the legacy strategy-preset registry; future research persistence belongs here or in a renamed research package. |
| `decision/strategies/` | Experimental hard-coded screens awaiting migration to serializable presets. |
| `decision/tools/` | Target location for the field registry, filters, ranker, and screen orchestration after branch work is merged. |
| `pipeline/setup_db.py` | Database extension and table creation. |
| `pipeline/load_data.py` | Initial Sharadar, technical-feature, and macro load. |
| `pipeline/daily_update.py` | Incremental data and feature updates. |
| `research/` | Target location for run persistence, replay, evaluation, dossiers, and thesis workflows. |

The legacy names `decision` and `strategy_profiles` may be renamed after the generic
screen pipeline is stable. Renaming is lower priority than establishing clear research
contracts.

## Data foundation

### Sources and tables

| Domain | Source | PostgreSQL table | Repository |
|---|---|---|---|
| Equity OHLCV | Sharadar SEP | `equity_prices` | `database/source/equity_repo.py` |
| Fund/ETF OHLCV | Sharadar SFP | `fund_prices` | `database/source/fund_repo.py` |
| Company metadata | Sharadar TICKERS | `tickers` | `database/source/tickers_repo.py` |
| Fundamentals | Sharadar SF1 | `fundamentals` | `database/source/fundamentals_repo.py` |
| Insider transactions | Sharadar SF2 | `insider_transactions` | `database/source/insider_repo.py` |
| Institutional holdings | Sharadar SF3 | `institutional_holdings` | `database/source/institutional_repo.py` |
| Corporate events | Sharadar EVENTS | `events` | `database/source/event_repo.py` |
| Technical features | Calculated from OHLCV | `technical_features` | `database/source/technical_features_repo.py` |
| Macro history | FRED | `macro` | `database/source/macro_repo.py` |

The initial history begins at `2016-01-01`. `pipeline/load_data.py` bulk-exports
Sharadar tables, loads PostgreSQL, calculates technical features for available price
history, and loads macro history.

`pipeline/daily_update.py` incrementally updates prices, technical features,
fundamentals, insider transactions, events, ticker metadata, institutional holdings,
and macro data.

Running `pipeline.setup_db` currently drops tables before recreating them. It is a
destructive bootstrap operation, not a routine migration command.

## Signal layer

All concrete signal classes inherit from `data.signals.sig.Signals`.

The service contract is:

```python
frame = SomeSignals.get_signals(..., signal_day)
frame = SomeSignals.attach_something(frame, ...)
```

Rules:

- `get_signals()` returns point-in-time rows with light shape and date normalization.
- Derived features are opt-in `attach_*()` methods.
- Attachments return a copy or a new DataFrame.
- Signal services retain no per-run instance state.
- Percentile ranks are direction-free facts in `[0, 100]`.
- Ranking direction and weights belong to a serializable research specification.

| Service | Purpose |
|---|---|
| `TechnicalSignals` | Latest price-derived features and relative-return context. |
| `FundamentalSignals` | Latest available fundamentals, calculated ratios, growth, and history features. |
| `EventSignals` | Recent filing/event codes and event recency. |
| `InsiderSignals` | Filing-safe transactions, purchase classification, and recent activity facts. |
| `InstitutionalSignals` | Conservatively available holdings and quarter-over-quarter ownership changes. |
| `MacroSignals` | Release-aware macro history, directional changes, and labor statistics. |

## Point-in-time requirements

Every screen, dossier, and replay must use only information available on or before its
`signal_day`.

Current protections include:

- technical rows constrained to `date <= signal_day`;
- a recent-trade requirement that prevents stale delisted rows from appearing active;
- fundamentals constrained by `datekey <= signal_day`;
- insider transactions constrained by filing date;
- events constrained to dates visible by the signal day;
- institutional holdings delayed by a conservative 45 days after quarter end; and
- release-sensitive macro series aligned to first-release availability.

Known limitations:

1. `tickers` contains current sector classifications rather than versioned sector
   history. Historical sector-relative ranks may contain classification look-ahead.
2. Institutional data does not retain every filing's actual acceptance timestamp. The
   45-day availability estimate is conservative but approximate.
3. Sharadar revision and restatement semantics require a focused audit to prove that
   revised historical fundamentals cannot overwrite the earlier information set.
4. Event lookback windows are bounded; a “days since” value means days since a matching
   event inside that window.
5. Five-year change features require roughly six years of annual history and are
   sparsely populated in early replay periods.

Every persisted research run must record:

- the requested signal date;
- the actual source-data cutoff or freshness;
- the full `ScreenSpec`;
- a model/specification version;
- coverage and missingness;
- every filter's attrition; and
- the evidence used to calculate each candidate score.

## Generic screening contract

A research screen consists of:

- a structural universe;
- zero or more elective filters;
- optional ranking sleeves;
- explicit cross-sleeve weights;
- direction overrides for ambiguous fields;
- an optional result cut such as top N by sector; and
- a name, description, and version.

The same serializable specification must be consumed by:

- the interactive screen builder;
- scheduled research runs;
- historical replay;
- saved-run inspection; and
- the AI research assistant.

This prevents the tested method from drifting away from the live screen.

Sector percentile ranks should be calculated over the structural comparison universe
before elective filters. Otherwise a score changes meaning whenever a filter is added
or removed.

### Universe specification fields

The universe specification controls the base security population. It contains
categorical security-master choices and point-in-time activity requirements, not
fundamental or technical opinions. The initial defaults reproduce a liquid US common
stock research population without forcing a market-cap, profitability, or momentum
view.

| Name | Allowed values or range | Datatype |
|---|---|---|
| `security_types` | One or more registered types; initially `common_stock` only. Future types may include `adr`, `preferred_stock`, `etf`, and `closed_end_fund` after their source coverage is validated. | `tuple[str, ...]` |
| `exchanges` | One or more registered exchange codes; initially `NYSE` and `NASDAQ`. OTC must require an explicit choice. | `tuple[str, ...]` |
| `include_tickers` | Zero or more normalized ticker symbols. Explicit includes must still satisfy point-in-time data-integrity rules. | `tuple[str, ...]` |
| `exclude_tickers` | Zero or more normalized ticker symbols. Exclusion wins if a symbol appears in both include and exclude lists. | `tuple[str, ...]` |
| `recent_trade_days` | Integer from `1` through `30`. Values above `10` should produce a stale-security warning. | `int` |

`countries`, `security_types`, and exchange values require a normalization layer over
the vendor metadata. A value is not offered to users until its mapping and historical
coverage have been validated.

### Filter field catalog

Every filter uses a registered field plus an operator and value. Numeric percentages
and returns are stored as decimal ratios unless the field explicitly says
“percentage points.” For example, `0.15` means 15%, while a 10-year Treasury yield of
`4.25` means 4.25 percentage points.

The common numeric operators are `<`, `<=`, `=`, `!=`, `>=`, `>`, and `between`.
Categorical fields use `in` and `not_in`; collection fields use `contains_any`,
`contains_all`, and `excludes_any`. Null handling must be explicit through `is_null` or
`not_null`; missing values never silently pass a numeric filter.

Fields marked † have source data and signal calculations but still need to be wired
into the generic screen engine. Macro fields marked ‡ apply to the entire research run,
not to individual companies: if the regime condition fails, the run has no candidates.

| Name | Valid value range | Datatype |
|---|---|---|
| `sector` | A registered sector label or set of labels; current labels are not historically versioned. | `str or null` |
| `industry` | A registered industry label or set of labels; current labels are not historically versioned. | `str or null` |
| `close` | `(0, +∞)` USD for the latest point-in-time close. | `float or null` |
| `marketcap` | `[0, +∞)` USD. | `float or null` |
| `dollar_volume_20d_avg` | `[0, +∞)` USD per session. | `float or null` |
| `volume_ratio` | `[0, +∞)`; current volume divided by its 50-session average. | `float or null` |
| `return_5d` | `[-1, +∞)` decimal return. | `float or null` |
| `return_20d` | `[-1, +∞)` decimal return. | `float or null` |
| `return_60d` | `[-1, +∞)` decimal return. | `float or null` |
| `return_252d` | `[-1, +∞)` decimal return. | `float or null` |
| `trend_slope_60d` | `(-∞, +∞)` annualized decimal slope. | `float or null` |
| `r_squared_60d` | `[0, 1]`. | `float or null` |
| `pct_from_sma_20` | `[-1, +∞)` decimal distance from the moving average. | `float or null` |
| `pct_from_sma_50` | `[-1, +∞)` decimal distance from the moving average. | `float or null` |
| `pct_from_sma_200` | `[-1, +∞)` decimal distance; derived from `close / sma_200 - 1`. | `float or null` |
| `pct_from_52w_high` | `[-1, 0]` decimal distance from the trailing high. | `float or null` |
| `drawdown_from_recent_high` | `[-1, 0]` decimal drawdown from the 20-session high. | `float or null` |
| `ema_crossover_days_ago` | `[0, +∞)` sessions. | `float or null` |
| `vol_adjusted_momentum` | `(-∞, +∞)` score. | `float or null` |
| `macd_hist` | `(-∞, +∞)` price-unit score. | `float or null` |
| `rsi_14` | `[0, 100]`. | `float or null` |
| `volatility_20` | `[0, +∞)` daily standard deviation. | `float or null` |
| `atr_pct` | `[0, +∞)` decimal average true range divided by price. | `float or null` |
| `consolidation_tightness` | `[0, +∞)` score; lower is tighter. | `float or null` |
| `pe` | `(-∞, +∞)`; values `<= 0` are valid loss-maker facts but undefined for “cheap P/E” ranking. | `float or null` |
| `ps` | `(-∞, +∞)`; positive values are required for conventional multiple ranking. | `float or null` |
| `pb` | `(-∞, +∞)`; positive values are required for conventional multiple ranking. | `float or null` |
| `evebitda` | `(-∞, +∞)`; positive values are required for conventional multiple ranking. | `float or null` |
| `fcf_yield` | Intended `(-∞, +∞)` decimal yield; the current calculation masks non-positive FCF and must be corrected before negative-FCF filtering is enabled. | `float or null` |
| `divyield` | `[0, +∞)` decimal yield. | `float or null` |
| `netinccmnusd` | `(-∞, +∞)` USD. | `float or null` |
| `gross_profitability` | `(-∞, +∞)`; gross profit divided by assets. | `float or null` |
| `roic` | `(-∞, +∞)` decimal return on invested capital. | `float or null` |
| `roe` | `(-∞, +∞)` decimal return on equity. | `float or null` |
| `roa` | `(-∞, +∞)` decimal return on assets. | `float or null` |
| `grossmargin` | `(-∞, +∞)` decimal margin. | `float or null` |
| `netmargin` | `(-∞, +∞)` decimal margin. | `float or null` |
| `ebitdamargin` | `(-∞, +∞)` decimal margin. | `float or null` |
| `cfo_to_assets` | `(-∞, +∞)` decimal ratio. | `float or null` |
| `accruals` | `(-∞, +∞)` decimal ratio; lower generally means more cash-backed earnings. | `float or null` |
| `interest_coverage` | `(-∞, +∞)` EBIT divided by interest expense. | `float or null` |
| `de` | `(-∞, +∞)` debt-to-equity ratio; negative equity can produce negative values. | `float or null` |
| `currentratio` | `[0, +∞)` current-assets-to-current-liabilities ratio. | `float or null` |
| `assetturnover` | `(-∞, +∞)` revenue-to-assets ratio. | `float or null` |
| `payoutratio` | `(-∞, +∞)` decimal payout ratio. | `float or null` |
| `roe_volatility_5y` | `[0, +∞)` five-year standard deviation; requires sufficient annual history. | `float or null` |
| `grossmargin_volatility_5y` | `[0, +∞)` five-year standard deviation; requires sufficient annual history. | `float or null` |
| `quality_history_observations` | `[0, +∞)` annual observations in the history window. | `int` |
| `complete_multi_year_history` | `true` or `false`; currently means at least six annual observations. | `bool` |
| `revenue_growth_yoy` | `(-∞, +∞)` decimal year-over-year growth. | `float or null` |
| `eps_growth_yoy` | `(-∞, +∞)` decimal year-over-year growth. | `float or null` |
| `opinc_growth_yoy` | `(-∞, +∞)` decimal year-over-year growth. | `float or null` |
| `grossmargin_change_yoy` | `(-∞, +∞)` decimal-point change. | `float or null` |
| `gross_profitability_change_5y` | `(-∞, +∞)` five-year ratio change; requires sufficient annual history. | `float or null` |
| `roa_change_5y` | `(-∞, +∞)` five-year ratio change; requires sufficient annual history. | `float or null` |
| `roic_change_5y` | `(-∞, +∞)` five-year ratio change; requires sufficient annual history. | `float or null` |
| `cfo_to_assets_change_5y` | `(-∞, +∞)` five-year ratio change; requires sufficient annual history. | `float or null` |
| `grossmargin_change_5y` | `(-∞, +∞)` five-year margin change; requires sufficient annual history. | `float or null` |
| `de_change_5y` | `(-∞, +∞)` five-year debt-to-equity change; requires sufficient annual history. | `float or null` |
| `net_payout_yield` | `(-∞, +∞)` decimal shareholder yield. | `float or null` |
| `share_dilution_5y` | `[-1, +∞)` five-year change in weighted-average shares; requires sufficient annual history. | `float or null` |
| `recent_event_codes` | Any subset of registered Sharadar event-code strings inside the configured lookback window. | `tuple[str, ...]` |
| `days_since_last_earnings` | `[0, event_lookback_days]`, or null when no matching event is visible in the window. | `int or null` |
| `days_since_last_activist_13d` | `[0, event_lookback_days]`, or null when no matching event is visible in the window. | `int or null` |
| `buy_count_30d` † | `[0, +∞)` open-market purchase transactions. | `int` |
| `buy_count_90d` † | `[0, +∞)` open-market purchase transactions. | `int` |
| `buy_value_30d` † | `[0, +∞)` USD. | `float` |
| `buy_value_90d` † | `[0, +∞)` USD. | `float` |
| `sell_count_30d` † | `[0, +∞)` open-market sale transactions. | `int` |
| `sell_count_90d` † | `[0, +∞)` open-market sale transactions. | `int` |
| `sell_value_30d` † | `[0, +∞)` USD. | `float` |
| `sell_value_90d` † | `[0, +∞)` USD. | `float` |
| `unique_buyers_30d` † | `[0, +∞)` distinct normalized owners. | `int` |
| `unique_sellers_30d` † | `[0, +∞)` distinct normalized owners. | `int` |
| `unique_opportunistic_buyers_30d` † | `[0, +∞)` distinct owners whose purchases are classified as non-routine. | `int` |
| `opportunistic_officer_buys_30d` † | `[0, +∞)` transactions. | `int` |
| `opportunistic_director_buys_30d` † | `[0, +∞)` transactions. | `int` |
| `opportunistic_buy_value_30d` † | `[0, +∞)` USD. | `float` |
| `max_purchase_fraction_of_post_holdings_30d` † | `[0, 1]` decimal fraction when holdings data is valid. | `float or null` |
| `opportunistic_value_to_marketcap` † | `[0, +∞)` decimal ratio. | `float or null` |
| `net_buy_ratio_90d` † | `[-1, 1]`; net open-market activity divided by gross activity. | `float or null` |
| `days_since_last_buy` † | `[0, +∞)` days, or null if no visible purchase exists. | `int or null` |
| `days_since_last_sell` † | `[0, +∞)` days, or null if no visible sale exists. | `int or null` |
| `institutional_stale_days` † | `[45, +∞)` days from the latest available quarter end. | `int or null` |
| `institutional_total_holders` † | `[0, +∞)` reporting institutions. | `int` |
| `institutional_total_value_b` † | `[0, +∞)` USD billions. | `float` |
| `institutional_holders_change` † | `(-∞, +∞)` quarter-over-quarter holder count change. | `int` |
| `institutional_value_change_pct` † | `[-1, +∞)` decimal quarter-over-quarter change. | `float or null` |
| `institutional_units_change_pct` † | `[-1, +∞)` decimal quarter-over-quarter change. | `float or null` |
| `institutional_new_holders` † | `[0, +∞)` institutions. | `int` |
| `institutional_closed_positions` † | `[0, +∞)` institutions. | `int` |
| `yield_curve_2_10` †‡ | `(-∞, +∞)` percentage-point spread. | `float or null` |
| `real_yield_10y` †‡ | `(-∞, +∞)` percentage points. | `float or null` |
| `fed_funds_rate` †‡ | `[0, +∞)` percentage points under normal data conventions. | `float or null` |
| `spread_hy` †‡ | `[0, +∞)` percentage points. | `float or null` |
| `spread_ig` †‡ | `[0, +∞)` percentage points. | `float or null` |
| `cpi_yoy` †‡ | `(-∞, +∞)` percentage points. | `float or null` |
| `unemployment_rate` †‡ | `[0, 100]` percentage points. | `float or null` |
| `claims_4w_avg` †‡ | `[0, +∞)` claims. | `float or null` |
| `claims_change_13w_pct` †‡ | `[-1, +∞)` decimal change. | `float or null` |
| `vix` †‡ | `[0, +∞)` index points. | `float or null` |
| `yield_curve_change_60d` †‡ | `(-∞, +∞)` percentage-point change. | `float or null` |
| `real_yield_change_20d` †‡ | `(-∞, +∞)` percentage-point change. | `float or null` |
| `spread_hy_change_20d` †‡ | `(-∞, +∞)` percentage-point change. | `float or null` |
| `spread_ig_change_20d` †‡ | `(-∞, +∞)` percentage-point change. | `float or null` |
| `vix_change_20d` †‡ | `(-∞, +∞)` index-point change. | `float or null` |
| `cpi_yoy_change_3m` †‡ | `(-∞, +∞)` percentage-point change. | `float or null` |

The first implementation should expose the fields already present in the generic field
registry, then add ownership fields, and add macro regime conditions last. Registering
a field requires a definition, source, unit, allowed operators, null semantics,
filterability, rankability, and coverage note; the UI must be generated from that same
metadata rather than maintaining a separate filter list.

### Generic ranking contract

The ranking engine answers one general question:

> Rank a population of entity X using one field Y or a weighted combination of fields
> Z.

It operates on a prepared entity-feature frame and does not retrieve or calculate
entity-specific facts. Security, institution, and holding feature builders may produce
different columns, but they use the same ranking algorithm.

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RankMetric:
    field: str
    direction: Literal["ascending", "descending"]
    weight: float = 1.0
    normalization: Literal[
        "percentile",
        "zscore",
        "robust_zscore",
        "raw",
    ] = "percentile"


@dataclass(frozen=True)
class RankSpec:
    entity_type: Literal["ticker", "institution", "holding"]
    metrics: tuple[RankMetric, ...]
    group_by: tuple[str, ...] = ()
    top_n: int | None = None
    missing_policy: Literal["renormalize", "exclude"] = "renormalize"
    minimum_coverage: float = 0.5
```

A single-metric rank uses one `RankMetric`:

```python
RankSpec(
    entity_type="ticker",
    metrics=(RankMetric("roic", "descending"),),
)
```

A composite rank normalizes its inputs before applying weights:

```python
RankSpec(
    entity_type="ticker",
    metrics=(
        RankMetric("roic", "descending", weight=0.40),
        RankMetric("fcf_yield", "descending", weight=0.30),
        RankMetric("de", "ascending", weight=0.30),
    ),
    group_by=("sector",),
    top_n=5,
)
```

For percentile normalization, the composite score is:

```text
score = sum(direction-adjusted percentile * weight)
        ------------------------------------------------
                 sum(available metric weights)
```

Ranking rules:

- weights must be finite and nonnegative;
- direction is independent of weight: lower-is-better uses `ascending`, never a
  negative weight;
- fields with incompatible units must be normalized before they are combined;
- `raw` normalization is allowed only when every combined metric is already on a
  commensurable scale;
- percentile and z-score reference populations are established before the final
  `top_n` cut;
- `group_by=("sector",)` means normalize and rank within sector;
- ties use a documented stable method and preserve the component values;
- missing values never become zero;
- `renormalize` divides by the weight actually available for an entity;
- `exclude` removes an entity missing any requested metric; and
- every result reports metric coverage even when it passes `minimum_coverage`.

The generic ranker accepts a feature frame indexed by a stable entity identifier:

```python
rank(
    frame: pd.DataFrame,
    spec: RankSpec,
    entity_id_column: str,
) -> RankResult
```

Its result contains:

```python
@dataclass
class RankResult:
    frame: pd.DataFrame
    spec: RankSpec
    population_size: int
    excluded_for_missingness: int
```

Every ranked row must expose:

| Field | Meaning |
|---|---|
| `entity_id` | Stable ticker, institution ID, or institution-ticker holding ID. |
| `rank` | Final ordinal rank inside the requested group. |
| `score` | Final normalized composite score. |
| `group` | Sector, industry, peer group, or null for a global rank. |
| `raw_values` | Frozen metric values before normalization. |
| `component_scores` | Direction-adjusted normalized value for every metric. |
| `available_weight` | Sum of requested weights with non-missing values. |
| `coverage` | Available weight divided by total requested weight. |

#### Entity-specific feature frames

The ranker is entity-agnostic. Feature builders establish the grain of each input row:

| Entity type | Row grain | Example ranking questions |
|---|---|---|
| `ticker` | One row per security | Highest ROIC; cheapest valuation; strongest weighted quality-and-momentum score. |
| `institution` | One row per reporting institution | Greatest exposure to a saved screen; most new positions; highest weighted quality of holdings. |
| `holding` | One row per institution-ticker pair | Largest portfolio weights; largest additions; highest-conviction new positions. |

Institutional holdings form a relationship:

```text
institution -> owns -> ticker
```

The same raw holdings can therefore be aggregated in three directions:

1. **Rank institutions** by portfolio concentration, exposure to a saved ticker set,
   new positions, or the weighted research scores of held companies.
2. **Rank tickers** by holder growth, institutional accumulation, new holders, or
   ownership by a selected institution set.
3. **Rank holdings** to inspect an institution's largest or fastest-changing
   institution-ticker positions.

A look-through institution score may use:

```text
institution_score =
    sum(position_portfolio_weight * held_ticker_research_score)
```

That score must record the referenced ticker screen/run ID, its specification version,
holding coverage, and the conservative institutional availability date. It may not use
holdings that were unavailable on the ranking date.

An example institution rank is:

```python
RankSpec(
    entity_type="institution",
    metrics=(
        RankMetric("screen_overlap_pct", "descending", 0.40),
        RankMetric("weighted_ticker_score", "descending", 0.35),
        RankMetric("new_positions_in_screen", "descending", 0.25),
    ),
    top_n=25,
)
```

The feature builders belong outside the ranking engine:

```text
research/
├── ranking.py
└── features/
    ├── securities.py
    ├── institutions.py
    └── holdings.py
```

`SLEntryScreener` currently combines responsibilities that the research platform keeps
separate:

| Current responsibility | Generic research component |
|---|---|
| Eligible tickers | `research/universe.py` |
| Signal and feature assembly | `research/features/securities.py` |
| Entry gates | `research/filters.py` |
| Sleeve and composite scoring | `research/ranking.py` |
| Top five per sector | `RankSpec.group_by` and `RankSpec.top_n` |
| Candidate snapshot | Persisted research-run result |
| Exit monitoring | Removed |

The `platform-pipeline` ranker is the starting point, but its public contract should
accept any entity-feature frame rather than assuming ticker rows and sector
percentiles.

### Holding policy contract

A holding policy defines what happens after a candidate enters a historical
simulation:

> Re-evaluate point-in-time conditions after entry and simulate a sale when the
> configured condition triggers.

It resembles the filter contract because it reuses registered fields, operators, and
typed values. Its semantics are different:

- an entry filter is evaluated once on the screen date;
- a holding condition is evaluated repeatedly after entry;
- a condition observed using session T data cannot execute at that same session's
  already-known close;
- the earliest simulated sale is the configured execution point on the following
  tradeable session; and
- no broker order or real position is created.

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HoldingCondition:
    field: str
    operator: str
    value: object
    consecutive_observations: int = 1


@dataclass(frozen=True)
class HoldingPolicy:
    exit_conditions: tuple[HoldingCondition, ...]
    combination: Literal["any", "all"] = "any"
    maximum_holding_sessions: int = 252
    minimum_holding_sessions: int = 0
    exit_timing: Literal["next_open", "next_close"] = "next_open"
```

Example:

```python
HoldingPolicy(
    exit_conditions=(
        HoldingCondition(
            field="pct_from_sma_200",
            operator="<",
            value=0,
            consecutive_observations=2,
        ),
        HoldingCondition(
            field="drawdown_from_entry_high",
            operator="<=",
            value=-0.20,
        ),
        HoldingCondition(
            field="recent_event_codes",
            operator="contains_any",
            value=("13", "31", "42"),
        ),
    ),
    combination="any",
    maximum_holding_sessions=252,
)
```

The first implementation should support:

| Policy type | Behavior |
|---|---|
| Fixed horizon | Exit after a configured number of trading sessions. This is the primary entry-quality test. |
| Feature condition | Exit when one or more registered point-in-time fields cross configured thresholds. |
| Rank condition | Exit when the security falls below a configured rank or percentile at a scheduled rerank. |
| Scheduled rebalance | Exit securities no longer selected at the weekly, monthly, or quarterly screen. |
| Earliest-of | Exit on the first configured condition or the maximum holding horizon, whichever arrives first. |

Holding conditions may reference the shared filter catalog or registered
evaluation-only state such as `days_held`, `return_from_entry`, and
`drawdown_from_entry_high`. Evaluation-only fields must be clearly labeled because
they depend on the simulated entry rather than source data alone.

Each simulated exit records:

| Field | Meaning |
|---|---|
| `entity_id` | Security being evaluated. |
| `entry_date` | First permitted session after the screen cutoff. |
| `entry_price` | Price established by the experiment's entry convention. |
| `exit_signal_date` | Date on which the holding condition became observable. |
| `exit_date` | Following tradeable session used for the simulated sale. |
| `exit_price` | Adjusted price used by the return calculation. |
| `exit_reason` | Stable condition or horizon identifier. |
| `exit_context` | Observed field values, operators, thresholds, and persistence counts. |
| `days_held` | Trading and calendar duration. |

Point-in-time safeguards:

- the holding evaluator sees only facts available on each observation date;
- conditions using a close execute no earlier than the following session;
- returns and drawdowns use split- and dividend-adjusted prices;
- delisted securities remain in the outcome set;
- missing condition data produces a warning or continued hold, never a fabricated
  trigger;
- the maximum horizon provides a deterministic fallback when conditional exits never
  fire; and
- the benchmark return uses the candidate's exact entry and exit interval.

Fixed-horizon evaluation must be run before conditional holding policies are optimized.
Otherwise, an elaborate exit rule can hide a universe or ranking model that adds no
entry value.

### Evaluation policy contract

An evaluation policy defines how a completed historical simulation is aggregated,
measured, and compared:

> Report the strategy by calendar week, month, and year; calculate rolling one-,
> three-, and five-year results; and compare every identical interval with buying and
> holding SPY.

```python
@dataclass(frozen=True)
class EvaluationPolicy:
    benchmark: str = "SPY"
    calendar_breakdowns: tuple[str, ...] = (
        "week",
        "month",
        "year",
    )
    rolling_windows: tuple[str, ...] = (
        "1y",
        "3y",
        "5y",
    )
    portfolio_weighting: Literal["equal_weight"] = "equal_weight"
    rebalance_frequency: Literal[
        "weekly",
        "monthly",
        "quarterly",
    ] = "monthly"
    exited_position_action: Literal[
        "hold_cash",
        "replace_next_rebalance",
        "replace_immediately",
    ] = "replace_next_rebalance"
    transaction_cost_bps: float = 0.0
```

`RankSpec.top_n` establishes how many candidates enter. The initial deterministic
simulation converts those candidates into a return series using this rule:

```text
select top N
    -> allocate equal weight
    -> rerun the saved screen monthly
    -> apply holding conditions after every eligible observation
    -> replace exits at the next monthly screen
    -> hold unused allocation as cash
```

This is a research portfolio used to make a strategy-level comparison possible. It is
not a recommended allocation, an automated portfolio manager, or an execution system.
More complex weighting must not be introduced until the equal-weight baseline is
understood.

Calendar reports contain:

```text
Period      Strategy return    SPY return    Excess return
2025-W01            +1.2%          +0.7%             +0.5%
2025-01             +3.4%          +2.6%             +0.8%
2025                +14.8%         +12.1%             +2.7%
```

Rolling reports contain:

```text
Window    Strategy CAGR    SPY CAGR    Excess CAGR
1 year            13.4%       11.2%          +2.2%
3 years           10.8%        9.7%          +1.1%
5 years            9.6%       10.1%          -0.5%
```

Every calendar period and rolling window reports:

- total return;
- compound annual growth rate when the period is at least one year;
- benchmark return over identical dates;
- excess return;
- annualized volatility;
- maximum drawdown;
- Sharpe ratio with its stated risk-free-rate assumption;
- positive-period hit rate;
- turnover;
- number of entries and exits;
- percentage of time and capital invested;
- transaction-cost impact;
- missing-data and delisting warnings; and
- the number of independent and overlapping observations.

The evaluator should also retain candidate-level outcomes—median return, dispersion,
hit rate, sector-relative return, and score-to-forward-return correlation—so a model's
selection quality is not hidden by portfolio construction.

The complete saved research experiment is:

```python
@dataclass(frozen=True)
class ExperimentSpec:
    screen: ScreenSpec
    holding: HoldingPolicy
    evaluation: EvaluationPolicy
```

Its execution flow is:

```text
materialize UniverseSpec
    -> apply entry filters
    -> apply RankSpec
    -> simulate equal-weight entries
    -> observe HoldingPolicy conditions through time
    -> simulate exits
    -> build the strategy return series
    -> report calendar week/month/year performance
    -> report rolling 1/3/5-year performance
    -> compare identical intervals with SPY buy-and-hold
```

Rolling three- and five-year windows overlap and are therefore not independent
observations. Reports must show overlapping results for continuity and non-overlapping
sample counts for statistical honesty. With source history beginning in 2016, five-year
evidence is inherently limited and must not be presented as a large sample.

## `sector_leaders`

`sector_leaders` is an experimental research preset. It is not a validated strategy and
must not be the platform's architectural center.

Its current research question is:

> Among liquid, profitable US companies already in an uptrend, which companies rank
> strongest within their sectors across trend quality, valuation, profitability,
> growth, and capital discipline?

Useful parts:

- a realistic end-to-end screen;
- explicit eligibility gates;
- sector-relative rankings;
- explainable sleeve scores;
- risk and event context; and
- a baseline for testing generic screen infrastructure.

Current problems:

- no reliable saved benchmark or ablation results;
- the previous evaluator used raw closes rather than adjusted total-return prices;
- the documented `$1B` market-cap floor disagrees with the implemented `$10B` constant;
- momentum appears in both eligibility and ranking;
- top-five-per-sector can retain weak absolute candidates;
- missing growth history changes the effective model over time;
- sleeve weights are unvalidated; and
- insider, institutional, and macro evidence are not integrated into its dossier.

Migration plan:

1. Express `sector_leaders_v0` as a serializable `ScreenSpec`.
2. Mark it `experimental` or `rejected`, never validated by default.
3. Verify candidate parity between the hard-coded implementation and generic engine on
   representative dates.
4. Remove trading-specific `ExitSnapshot` and `SLExitMonitor`.
5. Delete the hard-coded strategy after parity tests pass.
6. Preserve the preset and its evaluation history, including negative results.

## Research persistence

The first persistence model should contain four concepts.

### Research run

- run ID;
- screen specification and version;
- requested signal day;
- source-data cutoff/freshness;
- universe size and filter funnel;
- run timestamp and status; and
- coverage or data-quality warnings.

### Candidate snapshot

- run ID and symbol;
- final rank and score;
- component and sleeve scores;
- passed filters;
- missing fields;
- risk/context flags; and
- frozen evidence values and their effective dates.

### Thesis

- thesis ID and symbol;
- author and timestamps;
- claim and time horizon;
- supporting evidence;
- counterevidence;
- catalysts;
- invalidation conditions;
- confidence; and
- version history.

### Evaluation

- screen specification and version;
- replay dates and horizons;
- comparison universe and benchmarks;
- adjusted candidate and benchmark returns;
- coverage, turnover, and sample sizes;
- aggregate and per-sector results; and
- ablation or sensitivity results.

Research persistence must never require an order, position, or completed trade.

## Evaluation standards

The evaluator answers whether a research method adds information, not whether a
backtest can be optimized into an attractive chart.

Required comparisons:

1. structural universe versus market benchmark;
2. filtered universe versus structural universe;
3. ranked menu versus filtered universe;
4. sector picks versus their sector benchmark; and
5. each sleeve and filter versus the full specification.

Required safeguards:

- adjusted prices or total returns for candidates and benchmarks;
- entry strictly after the signal cutoff;
- delisted securities retained when they were historically eligible;
- full-horizon dates only;
- walk-forward or held-out evaluation;
- median, hit rate, dispersion, and sample size before mean return;
- turnover and coverage reporting;
- no silent treatment of missing values as zero;
- no parameter selection on the final evaluation period; and
- saved results for unsuccessful experiments.

A model should remain `experimental` until it shows stable incremental value over its
filtered universe, not merely positive absolute returns during a rising market.

## Product surfaces

The first interface should contain:

### Today

- scheduled research runs;
- newly qualifying and newly excluded companies;
- material score and evidence changes;
- coverage or stale-data warnings; and
- thesis alerts.

### Explore

- screen builder generated from the field catalog;
- filter funnel;
- ranked results;
- saved and versioned screen specifications; and
- side-by-side company comparison.

### Company

- fundamental, technical, ownership, event, and macro/sector evidence;
- current values and historical changes;
- sector and universe percentiles;
- source and effective dates;
- inclusion/exclusion explanations; and
- saved theses.

### Lab

- historical replay;
- baseline and benchmark comparison;
- sleeve/filter ablations;
- coverage and turnover diagnostics; and
- saved experiment results.

## Build order

### 1. Establish the generic screen engine

- merge and test the field registry, filters, ranker, and orchestrator;
- define a stable, serializable `ScreenSpec`;
- separate structural universe rules from elective research filters;
- produce an explicit filter funnel and missingness report; and
- migrate `sector_leaders_v0` to a preset.

### 2. Persist research runs

- create research-run and candidate-snapshot repositories;
- freeze specifications, scores, evidence, and effective dates;
- version saved screens; and
- make reruns idempotent for the same spec version and signal date.

### 3. Build trustworthy evaluation

- replace the deleted trading-oriented harness;
- use adjusted candidate and benchmark returns;
- measure filter lift separately from ranking lift;
- add walk-forward, per-sector, turnover, coverage, and ablation reports; and
- persist negative as well as positive results.

### 4. Expose the first vertical slice

- add a small API;
- implement Today, Explore, and Company;
- run and save one screen from the interface;
- open a candidate dossier with score provenance; and
- replay the exact saved specification from Lab.

### 5. Add thesis and monitoring workflows

- store versioned theses;
- capture supporting and opposing evidence;
- evaluate invalidation conditions against new runs;
- show evidence changes rather than only price alerts; and
- maintain a research journal.

### 6. Add grounded AI assistance

- let the assistant query registered fields and saved research;
- require citations to evidence values and dates;
- expose the exact generated `ScreenSpec` before execution;
- separate objective facts from generated interpretation; and
- prevent the assistant from claiming a model is validated without evaluation records.

## Verification

Current local checks:

```bash
PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/ruff check data database decision pipeline tests
.venv/bin/python -m compileall -q data database decision pipeline
```

As of 2026-07-26:

- `52 passed`;
- one third-party `websockets.legacy` deprecation warning remains; and
- the current sandbox could not connect to PostgreSQL for a historical replay.

Required next tests:

- invalid fields and ambiguous ranking directions are rejected;
- ranking percentiles are calculated over the intended comparison universe;
- a serialized and deserialized `ScreenSpec` produces identical results;
- a saved research run freezes the complete evidence used by every score;
- historical replay uses adjusted returns and never future information;
- filter lift and ranking lift are reported separately;
- missing data and coverage are visible;
- `sector_leaders_v0` parity holds before the hard-coded implementation is removed; and
- thesis alerts cite the exact changed facts and effective dates.

## First milestone

The first meaningful milestone is:

> A user chooses an as-of date, runs a saved screen, inspects a ranked and explainable
> candidate list, opens a company dossier, saves a thesis, and replays the exact same
> specification historically with point-in-time-safe evidence and adjusted benchmarks.

Real-time trading, brokerage integration, automated portfolio management, and execution
are not part of this milestone or the target architecture.
