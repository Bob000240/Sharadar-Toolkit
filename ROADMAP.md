# Sharadar Toolkit Roadmap

## Iteration 1: Sharadar Data Foundation — Complete

Goal: Load the required Sharadar datasets into PostgreSQL and keep them incrementally updated.

- [x] Connect to Nasdaq Data Link using an API key.
- [x] Define PostgreSQL source tables and repositories.
- [x] Implement the initial bulk historical load.
- [x] Implement filtered daily incremental updates.
- [x] Update existing rows when Sharadar revises data.
- [x] Include delisted securities to avoid survivorship bias.
- [x] Recompute technical features when price history changes.

## Iteration 2: Point-in-Time Signal Layer — Complete

Goal: Convert stored source data into objective, point-in-time research facts without embedding strategy judgments.

- [x] Create shared signal helpers for ratios, growth, and percentile ranks.
- [x] Retrieve the latest available technical features by signal date.
- [x] Retrieve filing-safe fundamentals and derive ratios, growth, and historical quality features.
- [x] Aggregate recent corporate events into ticker-level facts.
- [x] Retrieve filing-safe insider transactions.
- [x] Classify and aggregate insider purchase and sale activity.
- [x] Apply a conservative availability delay to institutional holdings.
- [x] Aggregate institutional holdings into ticker-level ownership changes.
- [x] Add tests for technical, fundamental, event, insider, and institutional signals.

## Iteration 3: Point-in-Time Screening Engine — In Progress

Goal: Turn point-in-time signals into configurable, explainable screening and ranking results.

- [x] Build the trading-session calendar.
- [x] Construct the structural security universe.
- [x] Create the filterable and rankable field registry.
- [x] Create the layer to orchestrate universe, filters, and ranking together.
- [ ] Expose a named screen through the command-line interface with an as-of date.
- [ ] Print the effective session, universe size, filter funnel, and ranked selections.
- [ ] Support exporting screen results for further analysis.
- [ ] Add an end-to-end test covering the command-line screening workflow.
- [ ] Document setup and the complete screening demonstration in the README.
