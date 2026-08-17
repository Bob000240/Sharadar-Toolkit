# Sharadar Toolkit Project Specification

Status: Draft — Milestone 1 Scope

## 1. Project Goal

Sharadar Toolkit transforms separate Sharadar Core datasets into an integrated, point-in-time equity research platform.

The platform first constructs a security universe from Sharadar ticker metadata. It then combines corporate events, fundamentals, equity prices, and derived technical features to filter and rank securities for any selected as-of date. The specific screening and ranking methods will remain configurable because the research approaches the platform should support have not yet been finalized.

The first version exposes these capabilities through a command-line interface.

## 2. Problem

Free brokerage research platforms such as Fidelity already provide strong tools for current stock screening, company research, analyst reports, and investment idea generation. Sharadar Toolkit is not intended to reproduce or replace those tools.

The project addresses the narrower need for a programmable and reproducible equity-research environment. A researcher should be able to define custom calculations, control exactly how securities are filtered and ranked, reconstruct the information available on a historical date, and replay the same research method without depending on a broker-defined interface or fixed set of criteria.

Existing brokerage tools do not provide the level of control required to connect raw pricing, fundamental, event, insider, and institutional records into a fully auditable point-in-time workflow. They are useful for current research, but they are not designed to serve as a researcher-controlled data platform on which custom experiments and future AI-assisted analysis can be built.

Sharadar Toolkit is justified only when its historical reproducibility, custom calculations, data integration, and programmatic access are used. For ordinary current-stock screening and analyst research, a free brokerage platform may remain the more appropriate tool.

## 3. Primary User

The primary user is the project author: an individual researcher and aspiring software/data engineer who wants to conduct configurable, point-in-time equity research through a command-line interface.

In addition to its research purpose, the project serves as a practical environment for developing and demonstrating:

- Data engineering skills through ingestion, normalization, incremental updates, and PostgreSQL storage.
- Software engineering skills through modular design, testing, documentation, and maintainable Python.
- Project-management skills through explicit scope, iterations, milestones, and definitions of done.
- Quantitative research skills through point-in-time screening, reproducible experiments, and bias-aware evaluation.
- AI integration skills through a future evidence-grounded research workflow.
- The ability to complete and present a substantial end-to-end technical project as part of a professional portfolio.

## 4. Core Use Cases

- Reconstruct which companies would have passed a screen on a historical date using only information available at that time.
- Include companies that were later delisted to reduce survivorship bias.
- Combine technical, valuation, profitability, and corporate-event signals in configurable screens.
- Inspect point-in-time insider and institutional ownership facts alongside screening results.
- Create custom weighted ranking models.
- Replay the same screen across multiple historical dates.
- Compare results before and after adding a filter or ranking metric.
- Record why each company passed, failed, or received its rank.
- Automate screens and experiments through Python.

## 5. Product Principles

Rules that guide every implementation decision.

- Point-in-time correctness
- Reproducibility
- Explainability
- Explicit missing-data handling
- Separation of objective facts from strategy judgments
- Research support rather than automated trading

## 6. Functional Requirements

### 6.1 Data Ingestion

- The system shall create the required PostgreSQL tables in an empty database.
- The system shall support an initial bulk load of every required Sharadar dataset.
- The initial load shall retain historical records for securities that were later delisted.
- The system shall support incremental updates that insert new records and update records revised by Sharadar.
- Repeating an incremental update shall not create duplicate source records.
- When equity-price history changes, the system shall recompute the affected technical features.
- A failed dataset update shall be reported clearly, and the update command shall return a nonzero exit status after attempting the remaining independent datasets.

### 6.2 Data Availability

- A historical query shall not use information that became available after its effective research date.
- Fundamental data shall be selected according to when it was filed or made available, rather than only by the fiscal period it describes.
- Event, insider, and institutional data shall use explicit availability rules appropriate to their publication delays.
- Delisted securities shall remain available when reconstructing a historical universe.
- Missing values shall remain missing and shall not be silently converted to zero.
- Every research result shall identify the trading session for which its data is effective.

### 6.3 Universe Construction

- The system shall construct the security universe independently for each effective research date.
- Universe membership shall be configurable by security type, exchange, explicit inclusions, explicit exclusions, and recent trading activity.
- The universe shall include only securities with a qualifying price record on or before the effective research date.
- A security that later became delisted shall remain eligible on earlier dates when it satisfied the configured universe rules.
- Invalid security types, exchanges, or recency settings shall be rejected before querying the database.
- The resulting universe shall contain no more than one row per security.

### 6.4 Signal Calculation

- The system shall derive technical signals from price information available on or before the effective research date.
- The system shall derive fundamental signals from the latest qualifying filing available on or before the effective research date.
- The system shall aggregate recent corporate events into ticker-level facts without exposing an event before its availability date.
- The signal layer shall retrieve and aggregate insider transactions using filing-safe dates.
- The signal layer shall retrieve institutional holdings using a conservative availability delay and shall support ticker-level ownership-change calculations.
- Milestone 1 shall make insider and institutional information available as standalone research facts; these fields are not required to participate in generic filtering or ranking.
- Derived ratios, growth rates, historical features, and percentile values shall be calculated deterministically from their source records.
- Screen execution shall calculate only the registered signal sources required by the selected filters and ranking metrics.
- Signal calculation shall produce objective research facts without deciding whether a value is inherently desirable.

### 6.5 Filtering

- The system shall support configurable filter conditions using registered filterable fields.
- The system shall support numeric comparisons, set membership, collection membership, ranges, and explicit null checks where appropriate to the field.
- When multiple filters are configured, a security shall qualify only when it passes every filter.
- The system shall reject unknown or non-filterable fields before querying research data.
- The system shall report how many securities were removed by each filter.
- For each filter, the system shall distinguish records removed because of missing data from records removed because their observed value failed the condition.
- A missing value shall fail an ordinary comparison unless the user explicitly selects a null-checking condition.

### 6.6 Ranking

- The system shall rank securities using configurable metrics, high-or-low directions, and positive weights.
- The system shall reject unknown or non-rankable fields before querying research data.
- Ranking metrics with different units shall be converted to comparable cross-sectional percentile values before being combined.
- Percentile scores shall be calculated over the structural universe before elective filters are applied so that a score retains the same meaning across screens.
- When a ranking value is missing, the system shall calculate the score from the available configured metrics and report the resulting coverage; the missing value shall not contribute a zero.
- Securities below the configured minimum metric coverage shall be excluded from ranking and reported.
- The system shall support ranking the entire result set or ranking separately within a configured group such as sector.
- The system shall support limiting results to the top configured number of securities overall or per group.

### 6.7 Screen Execution

- Given an as-of date and a valid screen configuration, the system shall combine universe construction, required signal calculation, filtering, and ranking into one run.
- If the requested as-of date is not a trading session, the system shall use and report the latest loaded trading session on or before that date.
- A date earlier than the loaded trading calendar shall be rejected rather than silently moved forward.
- A screen may omit elective filters, ranking, or both.
- When ranking is configured, the system shall return qualifying securities in ranked order.
- When ranking is not configured, the system shall return the qualifying securities without assigning scores or ranks.
- Running the same configuration against the same stored data shall produce the same result.

### 6.8 Results and Explainability

- Every result shall include the effective trading session, screen configuration, initial universe size, and final qualifying count.
- The result shall retain the signal values used by its filters and ranking metrics.
- Filtered results shall include an ordered funnel showing the condition, population before the condition, population after it, total removed, and number removed for missing data.
- Ranked results shall include each security's score, rank, metric coverage, and supporting percentile values.
- A valid screen with no qualifying securities shall return an empty result rather than fail.
- The CLI shall present a human-readable summary and shall support exporting the selected securities and their supporting values in a machine-readable format.

### 6.9 Historical Evaluation

- The system shall evaluate a selected population across a user-selected sequence of historical trading sessions.
- A population-selection rule shall be rebuilt independently on every evaluation date using the same point-in-time availability and universe rules used by a current screen.
- The system shall calculate forward returns from adjusted prices over explicitly configured trading-session horizons.
- A forward-return horizon that extends beyond the loaded price history shall be marked incomplete rather than treated as a complete zero return.
- Per-date evaluation output shall report the measured population size, mean return, hit rate, benchmark return, excess return, and measurement completeness.
- The system shall support comparing multiple population-selection variants over the same underlying universe and dates.

### 6.10 Command-Line Interface

- The command-line interface shall provide commands for database setup, initial data loading, incremental updating, and screen execution.
- The screen command shall accept an as-of date and a named screen configuration.
- Before executing a screen, the CLI shall report invalid dates, fields, operators, metric directions, weights, and universe settings with actionable messages.
- Successful screen execution shall print the screen name, effective trading session, universe size, filter funnel, and selected securities.
- The CLI shall support writing screen results to a user-selected output file.
- A command that cannot complete successfully shall return a nonzero exit status.

## 7. Milestone 1 Definition of Done

Milestone 1 is complete when:

- The required Sharadar data can be loaded into an empty PostgreSQL database and updated without creating duplicates.
- A named screen can be executed from the command line for a selected as-of date.
- The screen reports its effective trading session, universe size, filter funnel, selected securities, and ranking evidence.
- Screen results can be exported for further analysis.
- Automated tests cover the point-in-time data, signal, filtering, ranking, orchestration, and command-line workflow.
- The README contains sufficient setup and usage instructions to reproduce the demonstration.

## 8. Future Work

- Integrate insider and institutional ownership fields into generic filtering and ranking where useful.
- Add document ingestion and retrieval for SEC filings and other permitted research sources.
- Add an AI-assisted workflow that combines structured research facts with cited documentary evidence.
- Require AI explanations to identify uncertainty, distinguish interpretation from causation, and respect the selected as-of date.
- Add serialized user-defined screen configurations after the named-screen workflow is stable.
- Consider a graphical interface after the command-line workflow is complete.
