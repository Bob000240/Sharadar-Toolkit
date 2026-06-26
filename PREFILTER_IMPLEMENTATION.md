# QuorumNexus — Prefilter Suite Design & Build Plan

## The prefilter suite

| # | Prefilter | Universe | Best macro regime | Key flaws to mitigate | Signal files |
|---|---|---|---|---|---|
| 1 | `pre_value` | Broad small/mid + large | Early-cycle/reflation, rising rates, steepening curve | Value traps; sector concentration; sparse catalysts | `sig_fundamentals`, `sig_events`, `sig_sector_rotation`, `sig_macro` |
| 2 | `pre_quality` | S&P 500 | Late-cycle, risk-off, high-VIX, slowdowns | Expensive/crowded; lags junk rallies; inverse to Value | `sig_fundamentals`, `sig_macro` |
| 3 | `pre_momentum` (repair `pre_RS`) | S&P 500 | Persistent trends, mid-cycle, low/falling vol | Momentum crashes at inflections; turnover; **stale import** | `sig_technicals`, `sig_sector_rotation` |
| 4 | `pre_smartmoney` | Broad small/mid + large | Macro-insensitive; contrarian at capitulation lows; bear-market activism | Sparse/episodic; 45-day 13F/13G lag; 13G weak; **data-load check** | `sig_insider`, `sig_events`, `sig_institutional` |
| 5 | `pre_reversal` | S&P 500 / liquid mid | High-vol, range-bound, post-selloff bounces | Falling-knife risk → require quality gate; high turnover; opposes Momentum | `sig_technicals`, `sig_fundamentals`, `sig_events` |
| — | Macro overlay | all | n/a (regime tilt) | Regime detection lags | `sig_macro`, `sig_sector_rotation` |