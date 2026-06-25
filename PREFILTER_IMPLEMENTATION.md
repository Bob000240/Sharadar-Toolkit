# QuorumNexus — Prefilter Suite Design & Build Plan

## Context

QuorumNexus is a *deterministic prefilter → constrained agent → eval* trading-research
system (`PROJECT_CONCEPTS.md`). The deterministic layer screens a universe into candidate
packets with a risk envelope; the agent only chooses stop/target/timeline/size within that
envelope. Only one prefilter exists today (`pre_RS`, relative-strength momentum), and the
roadmap (`PROJECT_IMPLEMENTATION.md`, Phase 1→2) calls for a diversified set of deterministic
prefilters plus a multi-prefilter runner.

This plan builds out that set. The goal is **five lowly-correlated stock-picking sleeves**
spanning the major return engines (value, quality, momentum, event/smart-money, counter-trend)
plus **two cross-cutting overlays** (low-vol risk/sizing, macro regime). Decisions confirmed
with the user:

- **Universe = hybrid by strategy**: Momentum, Quality, Mean-Reversion run on the existing
  S&P 500 (liquid large-cap); Value and Smart-Money run on a broader small/mid-cap universe
  where their edge actually lives.
- **5th sleeve = Mean-Reversion prefilter**, with **Low-Vol as a risk/sizing overlay** (not a
  standalone sleeve — it overlaps Quality ~0.6–0.8 and doesn't fit the tactical ATR-stop
  machinery).
- **Insider/13D merges into one "Smart-Money Accumulation" prefilter** = insider open-market
  buys + 13D/13G events + 13F institutional net-buying.

### Two issues found during exploration (fix as part of this work)
1. **`pre_RS.py` has a broken import.** It imports `data_det.signals.sig_momentum`
   (`MomentumFactorsModel`), but the signal layer was refactored to `data/signals/sig_*.py`
   (the momentum module is now `sig_technicals.py` / `TechnicalsModel`). `data_det/` no longer
   exists. `pre_RS` must be re-pointed before it runs.
2. **SF2/SF3 data-load status is uncertain.** Exploration disagreed on whether
   `insider_transactions` (SF2) and `institutional_holdings` (SF3) are populated. Smart-Money
   depends on both — verify the tables have rows before building, and load via
   `data/sharadar_data.py` if empty.

## The prefilter suite

| # | Prefilter | Universe | Best macro regime | Key flaws to mitigate | Signal files |
|---|---|---|---|---|---|
| 1 | `pre_value` | Broad small/mid + large | Early-cycle/reflation, rising rates, steepening curve | Value traps; sector concentration; sparse catalysts | `sig_fundamentals`, `sig_events`, `sig_sector_rotation`, `sig_macro` |
| 2 | `pre_quality` | S&P 500 | Late-cycle, risk-off, high-VIX, slowdowns | Expensive/crowded; lags junk rallies; inverse to Value | `sig_fundamentals`, `sig_macro` |
| 3 | `pre_momentum` (repair `pre_RS`) | S&P 500 | Persistent trends, mid-cycle, low/falling vol | Momentum crashes at inflections; turnover; **stale import** | `sig_technicals`, `sig_sector_rotation` |
| 4 | `pre_smartmoney` | Broad small/mid + large | Macro-insensitive; contrarian at capitulation lows; bear-market activism | Sparse/episodic; 45-day 13F/13G lag; 13G weak; **data-load check** | `sig_insider`, `sig_events`, `sig_institutional` |
| 5 | `pre_reversal` | S&P 500 / liquid mid | High-vol, range-bound, post-selloff bounces | Falling-knife risk → require quality gate; high turnover; opposes Momentum | `sig_technicals`, `sig_fundamentals`, `sig_events` |
| — | Low-vol overlay | all | n/a (risk control) | Overfit risk | `sig_technicals` (volatility_20, atr_pct) |
| — | Macro overlay | all | n/a (regime tilt) | Regime detection lags | `sig_macro`, `sig_sector_rotation` |

## Architecture — every prefilter follows the `pre_RS` template

All five subclass `SignalAgent` (`decision_layer/det_layer/pre_filter.py`) and implement:
- `pre_filter(**kwargs) -> list[str]` — load the relevant `sig_*` model, build a sequence of
  boolean **gates**, compute a **cross-sectional percentile rank** for ordering, apply a
  per-sector cap, return the passing symbols. Mirror `pre_RS.pre_filter` (lines 51–92).
- `exit_signals(symbol) -> dict` — ATR-based stop/target/hold, like `pre_RS.exit_signals`
  (2×ATR stop, 3×ATR target; hold by entry mode). Reuse verbatim where the trade style matches.
- `run(symbol) -> AgentVerdict` — build the signal snapshot, synthesize reasoning, attach the
  exit envelope, return an `AgentVerdict`.

Reuse the existing snapshot methods rather than recomputing — each `sig_*` module already
exposes boolean flag dicts and a 0–1 composite score:

- **`sig_fundamentals`**: `valuation()`, `profitability()`, `earnings_quality()`,
  `balance_sheet()`, `growth()`, `efficiency()`, `quality_score()`, `risk_flags()`; percentile
  fields (`evebitda_percentile`, `roe_percentile`, `fcf_percentile`,
  `revenue_growth_percentile`); `marketcap` + large/mid tier flags.
- **`sig_events`**: `catalyst_flags()` (13D=35, 13G=34, M&A=21, tender=37, control=51),
  `risk_flags()` (delisting=31, bankruptcy=13, restatement=42, late filing=36, impairment=26),
  `days_to_next_earnings`.
- **`sig_insider`**: `cluster_buying()`, `officer_activity()`, `net_sentiment()`,
  `risk_flags()`, `insider_score()` (P/S codes only — already excludes grant/option noise).
- **`sig_institutional`**: `accumulation()`, `ownership_quality()`, `risk_flags()`,
  `institutional_score()` (already applies the 45-day filing-lag cutoff).
- **`sig_technicals`**: `momentum_score()`, `absolute_momentum()`, `relative_strength()`,
  `trend_quality()`, `oscillator_signals()` (RSI), `volatility_signals()`,
  `breakout_context()`, liquidity (`dollar_volume_20d_avg`), plus `rsi_14`,
  `pct_from_52w_high`, `pct_from_sma_20`, `volatility_20` for the reversal/low-vol logic.
- **`sig_sector_rotation`**: `sector_score()`, `sector_rank_20d`, `market_regime()`.
- **`sig_macro`**: `rate_environment()`, `credit_conditions()`, `inflation_regime()`,
  `risk_sentiment()`, `macro_score()`.

### Per-prefilter gate sketch
- **`pre_value`**: cheapness gate (low `evebitda_percentile` / PE/PB/PS via `valuation()`) +
  **catalyst** (`catalyst_flags()`: 13D/M&A/tender present or recent) + **trap guard**
  (exclude `sig_fundamentals.risk_flags()` losing-money / revenue-declining and
  `sig_events.risk_flags()` restatement/bankruptcy). Rank by composite cheapness percentile.
  Sector-neutralize via per-sector cap.
- **`pre_quality`**: `profitability()` + `earnings_quality()` + `balance_sheet_health()` all
  pass; rank by `quality_score()`. Exclude high-leverage / negative-FCF risk flags.
- **`pre_momentum`**: repaired `pre_RS` (re-point import to
  `data.signals.sig_technicals.TechnicalsModel`; reconcile field names). Optionally add
  explicit volatility scaling via existing `vol_adjusted_momentum`.
- **`pre_smartmoney`**: pass if any of {`cluster_buying()` strong, `officer_activity()` senior
  cluster, `catalyst_flags()` 13D/13G, `accumulation()` units fast-growing + net opening};
  rank by blended `insider_score()` + `institutional_score()`. Hard-reject `delisting`/
  `bankruptcy` from `sig_events.risk_flags()`.
- **`pre_reversal`**: oversold gate (`rsi_14` < ~30, deep `pct_from_52w_high`, below `sma_20`)
  + **quality floor** (`sig_fundamentals.profitability()` positive — avoids falling knives) +
  **event guard** (skip if earnings imminent / restatement). Rank by oversold magnitude. Short
  hold (tighter ATR target than momentum).

### Overlays (cross-cutting, not stock-pickers)
- **Low-vol**: a scoring/sizing function applied to candidates from any sleeve — prefer lower
  `volatility_20` / `atr_pct`, downsize high-vol names. Surfaces as a `risk_flag` and a
  position-size multiplier, not a separate candidate list.
- **Macro**: regime detector from `sig_macro` that tilts sleeve weighting (Value up in
  reflation, Quality up in slowdowns, Momentum sized down at high VIX / inflection). Apply at
  the runner level, not inside individual prefilters.

## Cross-cutting infrastructure work

1. **Hybrid universe** (`set_up/config.py`): add a broad small/mid-cap symbol list (from
   Sharadar `TICKERS`, filtered by `scalemarketcap` / `marketcap` tier and a
   `dollar_volume_20d_avg >= $5M` liquidity gate) alongside the existing `STOCK_SYMBOLS`
   (S&P 500). Each prefilter selects its universe per the table above.
2. **Repair `pre_RS`** import + field reconciliation against `data/signals/sig_technicals.py`.
3. **Verify/load SF2 & SF3** before `pre_smartmoney`.
4. **Register profiles**: one row per prefilter in `prefilter_profiles` via
   `prefilter_profiles_repository.upsert_profile` (name, version, default holding days,
   max_position_pct, max_loss_pct, allowed stop/target/timeline IDs).
5. **Emit candidates**: prefilters write to `screened_candidates` via
   `screened_candidates_repository.insert_candidate` (Phase 1→2 of the roadmap: move from
   prose output to table rows with `setup_score`, `passed_gates`, `risk_flags`, risk menu,
   `signal_context` JSONB). A thin multi-prefilter runner loops active profiles.

## Verification

- **Per-prefilter smoke test** (mirror `pre_RS.__main__`): `pre_filter()` returns a non-empty,
  sane-sized symbol list for its universe; `run(symbol)` returns a well-formed `AgentVerdict`
  with non-zero stop/target. Sanity bands: momentum/quality/value tens of names on S&P 500;
  `pre_smartmoney` will be small/episodic by design (a handful) — confirm it's non-zero on a
  date known to have 13D activity.
- **Point-in-time**: confirm each sleeve only reads `datekey/filingdate/date <= signal_day`
  (and the 45-day cutoff for 13F) — no lookahead. Spot-check by running on a historical
  `signal_day` and confirming no future-dated rows leak in.
- **Correlation check**: once each sleeve emits candidates over a backtest window, confirm the
  five candidate sets / returns are lowly correlated (the whole point of the suite). Flag if
  Value and Quality go strongly negative or Quality and the low-vol overlay collapse together.
- **Registry/output**: confirm each profile upserts to `prefilter_profiles` and produces rows
  in `screened_candidates` with populated risk menus.
- **End-to-end**: run the multi-prefilter runner for one `signal_day`; confirm candidates from
  all active sleeves land in `screened_candidates` ready for the agent layer.