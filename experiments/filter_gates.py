"""Which entry gates actually close the gap against SPY?

Eleven filter variants swept over quarterly signal days, each measured on
forward return versus a SPY buy-and-hold over the identical window. Lifted out
of research/filters.py, where it lived as a __main__ block.

Run: uv run python -m experiments.filter_gates
"""

import research.calendar as calendar
import research.signals.sig_events as sig_events
from research.evaluate.forward import ForwardReturns
from research.evaluate.walk_forward import WalkForward
from research.filters import Filters, attach_signals
from research.universe import Universe

SIGNAL_DAY = "2024-06-14"
universe = Universe()
base = universe.run(SIGNAL_DAY)
priced = attach_signals(base, SIGNAL_DAY)

print(f"\nFUNDAMENTALS COVERAGE on {SIGNAL_DAY}")
print(f"  universe          {len(base):,}")
print(f"  with marketcap    {priced.marketcap.notna().sum():,}")
print(f"  null marketcap    {priced.marketcap.isna().sum():,}")

print(f"\nFUNNEL on {SIGNAL_DAY} — the sector-leader $1B vs $10B question")
for label, floor in (
    ("alternative: $1B floor", 1_000_000_000),
    ("sector_leaders: $10B floor", 10_000_000_000),
):
    print(f"\n  {label}")
    funnel = Filters(("marketcap", ">=", floor)).funnel(priced)
    print(funnel.to_string(index=False))

SIGNAL_DAYS = calendar.schedule("2016-01-01", "2025-01-01", freq="QS")
forward = ForwardReturns(horizon_sessions=252)
walk = WalkForward(universe, forward, benchmark="SPY")

print(f"\nWALK-FORWARD: does a filter close the gap? ({len(SIGNAL_DAYS)} quarters)")

# Which codes disqualify is a strategy judgment, not a signal-layer fact:
# sig_events names the codes but takes no position on them.
_DISTRESS_CODES = (
    sig_events.BANKRUPTCY_CODE,
    sig_events.DELISTING_CODE,
    sig_events.RESTATEMENT_CODE,
    sig_events.LATE_FILING_CODE,
    sig_events.MATERIAL_IMPAIRMENT_CODE,
)

_FILTERS = {
    "no filter (baseline)": None,
    "$1B cap": Filters(("marketcap", ">=", 1e9)),
    "$10B cap": Filters(("marketcap", ">=", 1e10)),
    "profitable": Filters(("netinccmnusd", ">", 0)),
    "liquid >$5M/day": Filters(("dollar_volume_20d_avg", ">=", 5e6)),
    "above SMA200": Filters(("pct_from_sma_200", ">", 0)),
    "no distress events": Filters(
        ("recent_event_codes", "excludes_any", _DISTRESS_CODES)
    ),
    "distress events only": Filters(
        ("recent_event_codes", "contains_any", _DISTRESS_CODES)
    ),
    "$1B + profitable": Filters(("marketcap", ">=", 1e9), ("netinccmnusd", ">", 0)),
    "$1B + profitable + no distress": Filters(
        ("marketcap", ">=", 1e9),
        ("netinccmnusd", ">", 0),
        ("recent_event_codes", "excludes_any", _DISTRESS_CODES),
    ),
    "sector_leaders gates": Filters(
        ("dollar_volume_20d_avg", ">=", 5e6),
        ("marketcap", ">=", 1e10),
        ("netinccmnusd", ">", 0),
        ("return_60d", ">", 0),
        ("return_252d", ">", 0),
        ("pct_from_sma_200", ">", 0),
        ("trend_slope_60d", ">", 0),
    ),
    "sector_leaders + no distress": Filters(
        ("dollar_volume_20d_avg", ">=", 5e6),
        ("marketcap", ">=", 1e10),
        ("netinccmnusd", ">", 0),
        ("return_60d", ">", 0),
        ("return_252d", ">", 0),
        ("pct_from_sma_200", ">", 0),
        ("trend_slope_60d", ">", 0),
        ("recent_event_codes", "excludes_any", _DISTRESS_CODES),
    ),
}

results = walk.compare(SIGNAL_DAYS, _FILTERS, additions=attach_signals)
for label in _FILTERS:
    by_date = results[results.variant == label]
    if by_date.empty:
        continue
    summary = WalkForward.summarize(by_date)
    print(
        f"  {label:<30} measured(median)={by_date.measured.median():>6.0f}   "
        f"mean excess {summary['median_excess']:+.2%}   "
        f"dates beat bench {summary['pct_dates_beat_benchmark']:.1%}"
    )
