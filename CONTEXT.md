# Sharadar Toolkit — Context

Point-in-time equity research platform over Sharadar data. Reconstructs which
securities would have passed a screen on a historical date, using only the
information available on that date.

Solo project, PostgreSQL + pandas, CLI-first.

## Why it exists

Broker screeners (Fidelity et al.) already do *current* screening well. This is
not trying to replace them. It exists for the things they cannot do:
reconstructing a historical date honestly, custom calculations, and replaying
the same method programmatically.

**That framing decides scope.** Anything whose only use case is "screen as of
today" belongs to the broker screener, not here.

## Principles

These settle scope arguments. When a change conflicts with one, the principle wins.

- **Point-in-time correctness.** A historical query must not use information
  that became available after its effective date.
- **Explicit missing data.** Missing stays missing. Never zero-fill; a NaN must
  survive to the filter that would have used it.
- **Explainability.** Every result carries the evidence behind it — the funnel,
  the coverage, the percentiles.
- **Reproducibility.** The spec that was tested is the spec that runs.
- **Objective facts separated from strategy judgments.** The signal layer
  computes facts and takes no position on whether a value is desirable;
  `screens.py` holds the opinions.
- **Research support, not automated trading.** Screening and ranking answer
  "which securities are interesting." Position sizing, portfolio optimization,
  and order generation are out of scope.

## Architecture

```
data/          vendor API client (Sharadar via Nasdaq Data Link)
database/      Postgres persistence — one repo per vendor table
pipeline/      setup / load / update orchestration + CLI entry point
research/
  universe     structural eligibility (type, exchange, recency)
  signals/     point-in-time facts: technical, fundamental, event,
               insider, institutional
  registry     the field catalog — what may be screened or ranked on
  filters      field/operator/value predicates + attrition funnel
  ranking      weighted blend of percentile ranks
  orchestrator composes the above into one screen run
  screens      the named screens that ship
  evaluate/    forward returns, walk-forward, pluggable metrics
```

Dependency direction is one-way: `pipeline` → `research` → `database` → `data`.

## Decisions with reasons

Each of these cost real time to establish. Re-litigating them is expensive.

**Technical features are computed locally, not bought.** No vendor table carries
historical indicators. SHARADAR/METRICS looks like one but serves a
*one-row-per-ticker snapshot* — verified by API probe: ten years requested for
AAPL returned one row. Using it historically would return data only for
already-delisted companies, which is inverted survivorship. It was integrated,
measured, and removed.

**Precompute over compute-on-the-fly.** Benchmarked at ~8.9 ms/ticker: a
5,000-name universe costs ~45 s per screen on the fly versus ~0.15 s from the
`technical_features` table, and a 37-quarter walk-forward is 27 minutes versus
6 seconds. Ranking must score the *whole* structural universe before filtering,
so there is no shrinking the population to dodge this.

**Score before filter.** Percentiles are computed over the structural universe,
then elective filters apply. This makes a score of 82 mean the same thing across
screens; scoring after filtering would make every score relative to a different
reference set and silently incomparable.

**SF1 valuation is priced at the filing date.** `pe`, `ps`, `pb`, `marketcap`,
`evebit`, `evebitda` freeze *both* halves at `datekey`. The `*_daily` twins from
SHARADAR/DAILY reprice the market-cap half at the signal day — a stock that ran
61% since its last 10-Q shows P/E 13.7 in SF1 and 22.0 in DAILY. Prefer `_daily`
for valuation screens; SF1 remains the fallback where DAILY has no row
(9,622 tickers vs 13,285 in `equity_prices`).

**The registry is not just validation.** It also drives behavior
(`positive_only` masks loss-makers out of a rank rather than crowning them
cheapest), routing (`sources()` decides which derive chains run), and vocabulary
(labels, units, citations for a GUI or retrieval layer).

**Raw levels are deliberately unregistered.** Statement line items, moving
averages, and the price levels derived fields are built from. A raw `sma_200`
percentile ranks by share price; `pct_from_sma_50` does not. `close` is the one
exception, registered filter-only, because the universe enforces no price floor.

**Insider and institutional signals stay standalone.** Their `get_signals`
return raw transactions and holdings rather than one row per ticker, so they do
not fit the generic filter/rank path. Deliberate, not a gap.

**No portfolio optimizer.** Mean-variance weights answer "how many dollars of
each," which is implementation, not research. It would also need a QP solver.

## How evaluation works

`WalkForward` measures each date independently — a population is rebuilt,
measured over a forward horizon, and compared against SPY over the same window.
No portfolio is carried between dates, so it answers whether a selection *rule*
picks securities that outperform, not what an account holding them earned. There
is no compounding equity curve, rebalancing, or transaction costs.

Beyond the six baseline figures, `EvalMetric` plugs in more: rank quality
(information coefficient, top-minus-bottom decile) and concentration (average
pairwise correlation, sector Herfindahl). Concentration matters because a cut
can measure concentration while appearing to measure quality — that already
happened once with a roic/fcf_yield/accruals blend.

## Requirements

What the system must do. Behaviour here is covered by tests; treat a conflict
between this list and the code as a bug, not a licence to change the list.

### A.1 Data ingestion
- Create required PostgreSQL tables in an empty database
- Bulk-load every required Sharadar dataset, retaining records for
  later-delisted securities
- Incremental updates insert new records and update revised ones, without
  duplication on repeat runs
- Recompute affected technical features when equity-price history changes
- Report failed dataset updates clearly; return nonzero exit status after
  attempting the remaining independent datasets

### A.2 Data availability
- Historical queries must not use information that became available after the
  effective research date
- Fundamentals selected by filing/availability date, not fiscal period alone
- Event, insider, and institutional data use explicit availability rules
  matched to their publication delays
- Delisted securities remain available for historical universe reconstruction
- Missing values remain missing — never silently zero
- Every result identifies the trading session its data is effective for

### A.3 Universe construction
- Constructed independently per effective research date
- Configurable by security type, exchange, explicit inclusions/exclusions, and
  recent trading activity
- Only securities with a qualifying price record on or before the effective
  date are included
- Later-delisted securities remain eligible on earlier qualifying dates
- Invalid type/exchange/recency settings rejected before querying
- No more than one row per security

### A.4 Signal calculation
- Technical signals derived from price data available on or before the date
- Fundamental signals from the latest qualifying filing available by then
- Corporate events aggregated to ticker-level facts without exposing an event
  before its availability date
- Insider transactions retrieved and aggregated using filing-safe dates
- Institutional holdings retrieved using a conservative availability delay,
  supporting ownership-change calculations
- Insider/institutional exposed as standalone facts only — **not required to
  participate in generic filtering or ranking** (see Deferred)
- Derived ratios, growth rates, historical features, and percentiles calculated
  deterministically
- Screen execution calculates only the signal sources actually required
- Signals are objective facts — no desirability judgment

### A.5 Filtering
- Configurable conditions on registered filterable fields
- Numeric comparisons, set membership, collection membership, ranges, and
  explicit null checks
- A security qualifies only if it passes every configured filter
- Unknown or non-filterable fields rejected before querying
- Reports how many securities each filter removed
- Distinguishes removal for missing data from removal for a failed condition
- A missing value fails an ordinary comparison unless a null-checking condition
  is explicitly selected

### A.6 Ranking
- Configurable metrics, high/low direction, positive weights
- Unknown or non-rankable fields rejected before querying
- Metrics with different units converted to cross-sectional percentiles before
  combining
- Percentiles calculated over the **structural universe**, before elective
  filters apply, so a score means the same thing across screens
- A missing ranking value scores from the available metrics with coverage
  reported; it does not contribute a zero
- Securities below the configured minimum coverage are excluded and reported
- Ranking across the full set or within a group such as sector
- Top-N overall or per group

### A.7 Screen execution
- One run combines universe construction, required signal calculation,
  filtering, and ranking
- A non-session as-of date resolves to, and reports, the latest loaded session
  on or before it
- A date earlier than the loaded calendar is rejected, not moved forward
- Elective filters and ranking may each be omitted
- Ranked results come back in ranked order; unranked results carry no scores
- Same configuration and same stored data produce the same result

### A.8 Results and explainability
- Every result includes effective session, configuration, initial universe
  size, and final qualifying count
- Retains the signal values used by its filters and ranking metrics
- An ordered funnel: condition, population before and after, total removed, and
  removed-for-missing-data count
- Ranked results include score, rank, coverage, and supporting percentiles
- A valid screen with zero qualifying securities returns empty, not an error
- The CLI presents a readable summary and supports machine-readable export

### A.9 Historical evaluation
- Evaluate a selected population across a sequence of historical sessions,
  rebuilding it independently on each date under the same point-in-time rules
- Forward returns over configured session horizons; a horizon extending past
  the loaded history is marked incomplete, not treated as a zero return
- Per-date output reports measured population size, mean return, hit rate,
  benchmark return, excess return, and completeness
- Compare multiple population variants over the same universe and dates
- Additional per-date statistics are pluggable, covering rank quality and
  population concentration

Not built: significance testing. There is no t-statistic, p-value, or
confidence interval on any of the above — a median excess return is reported
without a claim about whether it is distinguishable from noise.

### A.10 Command-line interface
- Commands for database setup, initial load, incremental update, and screen
  execution
- The screen command accepts an as-of date and a named screen configuration
- Pre-execution validation of dates, fields, operators, directions, weights,
  and universe settings, with actionable messages
- Successful execution prints screen name, effective session, universe size,
  filter funnel, and selected securities
- Writes results to a user-selected output file
- A command that cannot complete returns a nonzero exit status

## Status

Research engine is complete and tested. Remaining for the first milestone, all
in `pipeline/`:

- a `screen` subcommand taking an as-of date and a named screen
- a presenter printing session, universe size, funnel, and selections
- export of results to a file
- an end-to-end test of the CLI workflow
- a README with setup and a reproducible demonstration

## Deferred

Not gaps — deliberately later:

- insider/institutional wired into generic filtering and ranking
- SEC document ingestion and retrieval
- an AI-assisted workflow combining structured facts with cited evidence,
  respecting the selected as-of date and distinguishing interpretation from
  causation
- user-defined serialized screen configurations
- a graphical interface
