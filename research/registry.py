"""The field catalog: one declarative description per selectable field.

This is the single source of truth about *what a user may screen or rank on*,
and it exists because that knowledge previously lived in four incompatible
places — dicts in the strategy, `positive_only` tuples, WHERE clauses in
eligibility SQL, and prose in docstrings. Every consumer now reads it from here:

  - `filters.validate` rejects unknown fields before a query is ever issued
  - `ranker` takes `direction` and `positive_only` from the field, not from
    strategy-level constants, so a user who picks `pe` gets the loss-maker
    masking automatically instead of silently ranking negative multiples as
    "cheapest"
  - a GUI generates its controls from `group`, `label`, `unit`, `coverage_note`
  - the retrieval layer embeds `description` + `citation` to map a natural
    language request onto real field keys

Deliberately NOT registered: raw statement line items (`assets`, `ncfo`,
`shareswa`) and moving-average levels (`sma_50`, `volume_sma_10`). They are
inputs to the derived fields below, not things anyone screens on directly — a
raw `sma_200` percentile is meaningless, whereas `pct_from_sma_50` is not. The
underlying columns remain available in the frame; they are simply not offered.

`direction` is None where no canonical better/worse exists: `volatility_20` is
rankable, but whether low or high is "good" depends on the question being asked,
so the caller must supply a direction rather than inherit a fake default.
"""

from dataclasses import dataclass

# ── field description ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    source: str                      # "technical" | "fundamental" | "event"
    direction: int | None = None     # +1 higher-is-better, -1 lower, None ambiguous
    unit: str = "ratio"              # ratio | pct | usd | days | count | score
    positive_only: bool = False      # non-positive is UNDEFINED, mask from ranks
    filterable: bool = True
    rankable: bool = True
    description: str = ""
    citation: str | None = None
    coverage_note: str | None = None

    @property
    def needs_direction(self) -> bool:
        """True when the field is rankable but has no canonical direction, so a
        caller must state which end it prefers."""
        return self.rankable and self.direction is None


# Every `*_change_5y` / `*_volatility_5y` needs ~6 years of annual history before
# it resolves, so all of them are effectively empty in early backtest windows.
_FIVE_YEAR = "Requires ~6y of annual history; largely unpopulated before ~2022."

_FIELDS = [
    # ── trend ────────────────────────────────────────────────────────────────
    Field("trend_slope_60d", "60-Day Trend Slope", "Trend", "technical", +1,
          description="Slope of the least-squares fit through 60 sessions of "
                      "closes. Positive means the trend is still rising rather "
                      "than merely having risen."),
    Field("r_squared_60d", "Trend Quality (R²)", "Trend", "technical", +1,
          unit="score",
          description="Fit quality of that 60-day regression: how smooth the "
                      "advance is rather than how large. Smooth trends attract "
                      "less attention and have historically continued longer.",
          citation="Da, Gurun & Warachka (2014), 'frog in the pan'"),
    Field("pct_from_sma_50", "% From 50-Day MA", "Trend", "technical", None,
          unit="pct",
          description="Distance of price above/below its 50-day average. "
                      "Extended in either direction, so no canonical direction."),
    Field("pct_from_sma_20", "% From 20-Day MA", "Trend", "technical", None,
          unit="pct",
          description="Distance above/below the 20-day average; short-term "
                      "stretch."),
    Field("pct_from_sma_200", "% From 200-Day MA", "Trend", "technical", None,
          unit="pct",
          description="Distance above/below the 200-day average — the "
                      "conventional primary-trend dividing line, so `> 0` is the "
                      "usual 'in an uptrend' test.",
          coverage_note="Derived in the screen from close and sma_200; not yet a "
                        "stored technical_features column."),
    Field("pct_from_52w_high", "% From 52-Week High", "Trend", "technical", +1,
          unit="pct",
          description="Proximity to the 52-week high. Nearer the high is "
                      "stronger; deep discounts here are broken trends, not "
                      "bargains."),
    Field("drawdown_from_recent_high", "Drawdown From Recent High", "Trend",
          "technical", -1, unit="pct",
          description="Decline from the most recent local peak."),
    Field("ema_crossover_days_ago", "Days Since EMA Crossover", "Trend",
          "technical", None, unit="days",
          description="Sessions since the 9/21-day EMA crossover. Small values "
                      "mark a fresh trend change in either direction."),

    # ── momentum ─────────────────────────────────────────────────────────────
    Field("return_252d", "12-Month Return", "Momentum", "technical", +1,
          unit="pct",
          description="Trailing one-year price return, the classic momentum "
                      "horizon.",
          citation="Jegadeesh & Titman (1993)"),
    Field("return_60d", "3-Month Return", "Momentum", "technical", +1,
          unit="pct", description="Trailing three-month price return."),
    Field("return_20d", "1-Month Return", "Momentum", "technical", None,
          unit="pct",
          description="Trailing one-month return. Direction is deliberately "
                      "unset: at this horizon the evidence points to short-term "
                      "reversal, not continuation.",
          citation="Jegadeesh (1990)"),
    Field("vol_adjusted_momentum", "Volatility-Adjusted Momentum", "Momentum",
          "technical", +1, unit="score",
          description="Trailing return scaled by realized volatility. Scaling "
                      "momentum by volatility materially improves its "
                      "risk-adjusted performance and reduces crash exposure.",
          citation="Barroso & Santa-Clara (2015)"),
    Field("macd_hist", "MACD Histogram", "Momentum", "technical", +1,
          unit="score",
          description="MACD minus its signal line; momentum acceleration."),
    Field("rsi_14", "RSI (14)", "Momentum", "technical", None, unit="score",
          description="14-day Relative Strength Index. A state, not a quality — "
                      "high can mean strength or exhaustion, so direction is "
                      "for the caller to choose."),

    # ── volatility & risk ────────────────────────────────────────────────────
    Field("volatility_20", "20-Day Volatility", "Volatility", "technical", None,
          unit="pct",
          description="Realized standard deviation of daily returns over 20 "
                      "sessions. Strongly persistent, which makes it the most "
                      "forecastable quantity here — but whether low or high is "
                      "wanted depends on the objective."),
    Field("atr_pct", "ATR %", "Volatility", "technical", None, unit="pct",
          description="Average True Range as a fraction of price: typical daily "
                      "range, the natural unit for stop placement."),
    Field("consolidation_tightness", "Consolidation Tightness", "Volatility",
          "technical", -1, unit="score",
          description="How tight the recent price base is. Lower means a "
                      "quieter base."),

    # ── liquidity & size ─────────────────────────────────────────────────────
    Field("dollar_volume_20d_avg", "Avg Dollar Volume (20d)", "Liquidity",
          "technical", +1, unit="usd",
          description="Mean daily traded value over 20 sessions — the practical "
                      "constraint on position size."),
    Field("volume_ratio", "Volume Ratio", "Liquidity", "technical", None,
          description="Current volume against its recent average; unusual "
                      "activity in either direction."),
    Field("marketcap", "Market Cap", "Size", "fundamental", None, unit="usd",
          description="Point-in-time market capitalization from the latest ART "
                      "filing available on the signal date."),

    # ── valuation ────────────────────────────────────────────────────────────
    Field("pe", "P/E", "Valuation", "fundamental", -1, positive_only=True,
          description="Price to earnings. Non-positive is undefined, not cheap: "
                      "a loss-maker has no meaningful P/E and is masked from "
                      "ranks rather than ranked cheapest."),
    Field("ps", "P/S", "Valuation", "fundamental", -1, positive_only=True,
          description="Price to sales. Defined wherever revenue is positive, so "
                      "it survives loss-making years that void P/E."),
    Field("pb", "P/B", "Valuation", "fundamental", -1, positive_only=True,
          description="Price to book. Negative book value is undefined, and it "
                      "understates asset-light firms whose value is intangible."),
    Field("evebitda", "EV/EBITDA", "Valuation", "fundamental", -1,
          positive_only=True,
          description="Enterprise value to EBITDA — capital-structure neutral, "
                      "so it compares across differing leverage."),
    Field("fcf_yield", "FCF Yield", "Valuation", "fundamental", +1, unit="pct",
          description="Free cash flow over market cap. Harder to manipulate than "
                      "earnings-based multiples, and meaningful when negative."),
    Field("divyield", "Dividend Yield", "Valuation", "fundamental", None,
          unit="pct",
          description="Trailing dividend yield. High yield can signal value or "
                      "distress, so direction is the caller's."),

    # ── profitability ────────────────────────────────────────────────────────
    Field("gross_profitability", "Gross Profitability", "Profitability",
          "fundamental", +1,
          description="Gross profit divided by total assets. Measured this high "
                      "on the income statement it is less contaminated by "
                      "accounting choices than net income, and predicts returns "
                      "about as well as book-to-market.",
          citation="Novy-Marx (2013)"),
    Field("roic", "Return on Invested Capital", "Profitability", "fundamental",
          +1, description="Return on capital actually employed in operations — "
                          "the cleanest single read on business quality."),
    Field("roe", "Return on Equity", "Profitability", "fundamental", +1,
          description="Net income over shareholders' equity. Inflated by "
                      "leverage, so it pairs poorly with debt screens."),
    Field("roa", "Return on Assets", "Profitability", "fundamental", +1,
          description="Net income over total assets; leverage-neutral."),
    Field("grossmargin", "Gross Margin", "Profitability", "fundamental", +1,
          unit="pct", description="Gross profit as a share of revenue — pricing "
                                  "power and cost structure."),
    Field("netmargin", "Net Margin", "Profitability", "fundamental", +1,
          unit="pct", description="Net income as a share of revenue."),
    Field("ebitdamargin", "EBITDA Margin", "Profitability", "fundamental", +1,
          unit="pct",
          description="EBITDA over revenue; comparable across tax and "
                      "depreciation regimes."),
    Field("cfo_to_assets", "Cash Flow to Assets", "Profitability", "fundamental",
          +1, description="Operating cash flow over assets: profitability that "
                          "has actually been collected in cash."),
    Field("netinccmnusd", "Net Income (Common, USD)", "Profitability",
          "fundamental", +1, unit="usd", rankable=False,
          description="Net income attributable to common shareholders, in USD. "
                      "Offered as a filter — `> 0` is the standard profitability "
                      "gate — but not for ranking, where an absolute dollar "
                      "amount would just rank by company size."),

    # ── quality & accounting ─────────────────────────────────────────────────
    Field("accruals", "Accruals", "Quality", "fundamental", -1,
          description="(Net income − operating cash flow) / assets. The wedge "
                      "between reported profit and cash. Firms with high "
                      "accruals systematically underperform, so lower is "
                      "better.",
          citation="Sloan (1996); cash-flow form per Hribar & Collins (2002)"),
    Field("interest_coverage", "Interest Coverage", "Quality", "fundamental", +1,
          description="EBIT over interest expense — how comfortably debt "
                      "service is met. Negative values are meaningful (a loss "
                      "against real interest), so they are not masked."),
    Field("de", "Debt / Equity", "Quality", "fundamental", -1,
          description="Total debt over equity. Balance-sheet risk."),
    Field("currentratio", "Current Ratio", "Quality", "fundamental", +1,
          description="Current assets over current liabilities; near-term "
                      "solvency."),
    Field("assetturnover", "Asset Turnover", "Quality", "fundamental", +1,
          description="Revenue over assets — how hard the asset base works. The "
                      "efficiency half of a margin/turnover decomposition."),
    Field("payoutratio", "Payout Ratio", "Quality", "fundamental", None,
          unit="pct",
          description="Dividends as a share of earnings. Very high payout is "
                      "fragile; very low may mean reinvestment or hoarding."),
    Field("roe_volatility_5y", "ROE Volatility (5y)", "Quality", "fundamental",
          -1, description="Standard deviation of ROE across five years — "
                          "earnings stability. Stable profitability is a core "
                          "component of quality factors.",
          citation="Asness, Frazzini & Pedersen (2019), 'Quality Minus Junk'",
          coverage_note=_FIVE_YEAR),
    Field("grossmargin_volatility_5y", "Gross Margin Volatility (5y)", "Quality",
          "fundamental", -1,
          description="Five-year dispersion of gross margin; pricing stability.",
          coverage_note=_FIVE_YEAR),

    # ── growth ───────────────────────────────────────────────────────────────
    Field("revenue_growth_yoy", "Revenue Growth (YoY)", "Growth", "fundamental",
          +1, unit="pct", description="Year-over-year revenue change."),
    Field("eps_growth_yoy", "EPS Growth (YoY)", "Growth", "fundamental", +1,
          unit="pct",
          description="Year-over-year earnings-per-share change; share-count "
                      "aware, so buybacks flatter it."),
    Field("opinc_growth_yoy", "Operating Income Growth (YoY)", "Growth",
          "fundamental", +1, unit="pct",
          description="Year-over-year operating income change — below revenue, "
                      "above financing and tax noise."),
    Field("grossmargin_change_yoy", "Gross Margin Change (YoY)", "Growth",
          "fundamental", +1, unit="pct",
          description="Year-over-year gross margin expansion."),
    Field("gross_profitability_change_5y", "Gross Profitability Trend (5y)",
          "Growth", "fundamental", +1,
          description="Five-year change in gross profitability: improving "
                      "quality rather than a single-period level.",
          coverage_note=_FIVE_YEAR),
    Field("roic_change_5y", "ROIC Trend (5y)", "Growth", "fundamental", +1,
          description="Five-year change in return on invested capital.",
          coverage_note=_FIVE_YEAR),
    Field("cfo_to_assets_change_5y", "Cash Flow to Assets Trend (5y)", "Growth",
          "fundamental", +1,
          description="Five-year change in cash-based profitability.",
          coverage_note=_FIVE_YEAR),
    Field("grossmargin_change_5y", "Gross Margin Trend (5y)", "Growth",
          "fundamental", +1, unit="pct",
          description="Five-year gross margin expansion.",
          coverage_note=_FIVE_YEAR),
    Field("de_change_5y", "Debt / Equity Trend (5y)", "Growth", "fundamental",
          -1, description="Five-year change in leverage; rising is worse.",
          coverage_note=_FIVE_YEAR),

    # ── capital discipline ───────────────────────────────────────────────────
    Field("net_payout_yield", "Net Payout Yield", "Capital Discipline",
          "fundamental", +1, unit="pct",
          description="Dividends plus net buybacks over market cap. Captures "
                      "total cash returned, unlike dividend yield alone.",
          citation="Boudoukh et al. (2007)"),
    Field("share_dilution_5y", "Share Dilution (5y)", "Capital Discipline",
          "fundamental", -1, unit="pct",
          description="Five-year growth in shares outstanding. Net issuers "
                      "underperform net repurchasers; lower is better.",
          citation="Pontiff & Woodgate (2008)",
          coverage_note=_FIVE_YEAR),

    # ── events (filter-only) ─────────────────────────────────────────────────
    Field("recent_event_codes", "Recent Event Codes", "Events", "event",
          unit="count", rankable=False,
          description="Deduped Sharadar 8-K event codes filed in the lookback "
                      "window. Use with `excludes_any` to drop distress "
                      "signals — delisting (31), bankruptcy (13), restatement "
                      "(42), late filing (36), material impairment (26)."),
    Field("days_since_last_earnings", "Days Since Earnings", "Events", "event",
          unit="days", rankable=False,
          description="Sessions since the last earnings release. Small values "
                      "mean the price is still digesting a report."),
    Field("days_since_last_activist_13d", "Days Since 13D Filing", "Events",
          "event", unit="days", rankable=False,
          description="Sessions since the last Schedule 13D activist filing."),
]

FIELDS: dict[str, Field] = {field.key: field for field in _FIELDS}


# ── accessors ────────────────────────────────────────────────────────────────


def get(key: str) -> Field:
    """Look up one field, raising with the key spelled out — the error a GUI or
    an agent that invented a field name should see."""
    try:
        return FIELDS[key]
    except KeyError:
        raise KeyError(f"unknown field {key!r}; {len(FIELDS)} registered") from None


def unknown(keys) -> list[str]:
    """The subset of `keys` that is not registered. Cheap pre-query validation."""
    return [key for key in keys if key not in FIELDS]


def rankable() -> dict[str, Field]:
    return {key: f for key, f in FIELDS.items() if f.rankable}


def filterable() -> dict[str, Field]:
    return {key: f for key, f in FIELDS.items() if f.filterable}


def by_group() -> dict[str, list[Field]]:
    """Fields bucketed by group, in registration order — the shape a GUI needs to
    render grouped controls."""
    groups: dict[str, list[Field]] = {}
    for field in _FIELDS:
        groups.setdefault(field.group, []).append(field)
    return groups


def sources(keys) -> set[str]:
    """Which derive chains a set of fields requires ("technical", "fundamental",
    "event"), so a screen only computes what it is asked for."""
    return {get(key).source for key in keys}


def positive_only(keys) -> tuple[str, ...]:
    """The subset needing non-positive masking before ranking — what the ranker
    passes to `attach_sector_ranks` instead of a hardcoded constant."""
    return tuple(key for key in keys if get(key).positive_only)
