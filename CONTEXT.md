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

## Evaluation

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
