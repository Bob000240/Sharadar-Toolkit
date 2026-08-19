"""The field catalog: one declarative description per selectable field.

The single source of truth about what a user may screen or rank on. It exists
because that knowledge once lived in four incompatible places — strategy dicts,
``positive_only`` tuples, eligibility SQL, and docstrings.

Consumers: ``orchestrator.validate`` rejects unknown fields, the ranker takes
``direction`` and ``positive_only`` from the field rather than a strategy
constant, ``sources`` decides which derive chains run, and a GUI or retrieval
layer reads the prose.

Raw inputs are deliberately unregistered — statement line items, moving-average
levels, and the price levels derived fields are built from. A raw ``sma_200``
percentile is meaningless where ``pct_from_sma_50`` is not. ``close`` is the
exception, filter-only, because the universe enforces no price floor.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """One declarative description of a field a user may screen or rank on.

    ``key`` is the frame column, ``group`` buckets it for a control, and ``source``
    names the derive chain: "technical", "fundamental", or "event".

    ``direction`` is +1, -1, or None where no canonical better end exists — a sign
    only, never a magnitude. ``positive_only`` marks a field whose non-positive
    values are undefined rather than extreme, so they are masked out of a rank.

    ``allowed_operators`` is None for every scalar operator; only a field whose
    cells are not scalars needs it, since ``>=`` against a list silently empties a
    screen rather than erroring. ``value_type`` marks a type category, not a
    storage width — counts stay ``float`` because every numeric column is nullable.
    """

    key: str
    label: str
    group: str
    source: str
    direction: int | None = None
    unit: str = "ratio"
    positive_only: bool = False
    filterable: bool = True
    rankable: bool = True
    allowed_operators: frozenset[str] | None = None
    value_type: type = float
    description: str = ""
    citation: str | None = None
    coverage_note: str | None = None

    @property
    def needs_direction(self) -> bool:
        """Return True when a caller must supply a direction for this field.

        That is, when the field is rankable but has no canonical better end.
        """
        return self.rankable and self.direction is None


_FIVE_YEAR = "Requires ~6y of annual history; largely unpopulated before ~2022."

_WITHIN_FRAME = (
    "Ranked across the population being screened, not the whole market, so the "
    "same security scores differently under a different universe."
)

_VENDOR_DAILY = (
    "Sourced from the daily_valuation table (SHARADAR/DAILY); every value is "
    "null until that table is loaded."
)

_FIELDS = [
    Field(
        "trend_slope_60d",
        "60-Day Trend Slope",
        "Trend",
        "technical",
        +1,
        description="Slope of the least-squares fit through 60 sessions of "
        "closes. Positive means the trend is still rising rather "
        "than merely having risen.",
    ),
    Field(
        "r_squared_60d",
        "Trend Quality (R²)",
        "Trend",
        "technical",
        +1,
        unit="score",
        description="Fit quality of that 60-day regression: how smooth the "
        "advance is rather than how large. Smooth trends attract "
        "less attention and have historically continued longer.",
        citation="Da, Gurun & Warachka (2014), 'frog in the pan'",
    ),
    Field(
        "pct_from_sma_50",
        "% From 50-Day MA",
        "Trend",
        "technical",
        None,
        unit="pct",
        description="Distance of price above/below its 50-day average. "
        "Extended in either direction, so no canonical direction.",
    ),
    Field(
        "pct_from_sma_20",
        "% From 20-Day MA",
        "Trend",
        "technical",
        None,
        unit="pct",
        description="Distance above/below the 20-day average; short-term stretch.",
    ),
    Field(
        "pct_from_sma_200",
        "% From 200-Day MA",
        "Trend",
        "technical",
        None,
        unit="pct",
        description="Distance above/below the 200-day average — the "
        "conventional primary-trend dividing line, so `> 0` is the "
        "usual 'in an uptrend' test.",
        coverage_note="Derived in the screen from close and sma_200; not yet a "
        "stored technical_features column.",
    ),
    Field(
        "pct_from_52w_high",
        "% From 52-Week High",
        "Trend",
        "technical",
        +1,
        unit="pct",
        description="Proximity to the 52-week high. Nearer the high is "
        "stronger; deep discounts here are broken trends, not "
        "bargains.",
    ),
    Field(
        "drawdown_from_recent_high",
        "Drawdown From Recent High",
        "Trend",
        "technical",
        -1,
        unit="pct",
        description="Decline from the most recent local peak.",
    ),
    Field(
        "ema_crossover_days_ago",
        "Days Since EMA Crossover",
        "Trend",
        "technical",
        None,
        unit="days",
        description="Sessions since the 9/21-day EMA crossover. Small values "
        "mark a fresh trend change in either direction.",
    ),
    Field(
        "return_252d",
        "12-Month Return",
        "Momentum",
        "technical",
        +1,
        unit="pct",
        description="Trailing one-year price return, the classic momentum horizon.",
        citation="Jegadeesh & Titman (1993)",
    ),
    Field(
        "return_60d",
        "3-Month Return",
        "Momentum",
        "technical",
        +1,
        unit="pct",
        description="Trailing three-month price return.",
    ),
    Field(
        "return_20d",
        "1-Month Return",
        "Momentum",
        "technical",
        None,
        unit="pct",
        description="Trailing one-month return. Direction is deliberately "
        "unset: at this horizon the evidence points to short-term "
        "reversal, not continuation.",
        citation="Jegadeesh (1990)",
    ),
    Field(
        "return_5d",
        "1-Week Return",
        "Momentum",
        "technical",
        None,
        unit="pct",
        description="Trailing one-week return. Direction is unset for the same "
        "reason as the one-month horizon: this short, reversal "
        "dominates continuation.",
    ),
    Field(
        "vol_adjusted_momentum",
        "Volatility-Adjusted Momentum",
        "Momentum",
        "technical",
        +1,
        unit="score",
        description="Trailing return scaled by realized volatility. Scaling "
        "momentum by volatility materially improves its "
        "risk-adjusted performance and reduces crash exposure.",
        citation="Barroso & Santa-Clara (2015)",
    ),
    Field(
        "macd_hist",
        "MACD Histogram",
        "Momentum",
        "technical",
        +1,
        unit="score",
        description="MACD minus its signal line; momentum acceleration.",
    ),
    Field(
        "rsi_14",
        "RSI (14)",
        "Momentum",
        "technical",
        None,
        unit="score",
        description="14-day Relative Strength Index. A state, not a quality — "
        "high can mean strength or exhaustion, so direction is "
        "for the caller to choose.",
    ),
    Field(
        "return_5d_percentile",
        "1-Week Return Percentile",
        "Momentum",
        "technical",
        None,
        unit="score",
        rankable=False,
        description="Cross-sectional percentile of the one-week return.",
        coverage_note=_WITHIN_FRAME,
    ),
    Field(
        "return_20d_percentile",
        "1-Month Return Percentile",
        "Momentum",
        "technical",
        None,
        unit="score",
        rankable=False,
        description="Cross-sectional percentile of the one-month return.",
        coverage_note=_WITHIN_FRAME,
    ),
    Field(
        "return_60d_percentile",
        "3-Month Return Percentile",
        "Momentum",
        "technical",
        +1,
        unit="score",
        rankable=False,
        description="Cross-sectional percentile of the three-month return. "
        "`>= 80` is how a top-quintile momentum gate is written.",
        coverage_note=_WITHIN_FRAME,
    ),
    Field(
        "return_252d_percentile",
        "12-Month Return Percentile",
        "Momentum",
        "technical",
        +1,
        unit="score",
        rankable=False,
        description="Cross-sectional percentile of the one-year return.",
        coverage_note=_WITHIN_FRAME,
    ),
    Field(
        "excess_return_5d",
        "Excess Return (1w, vs SPY)",
        "Momentum",
        "technical",
        +1,
        unit="pct",
        description="One-week return less the benchmark's over the same span, "
        "which separates a security that rose from one that rose "
        "because everything did.",
        coverage_note="Null when the benchmark fund lacks the history; the "
        "benchmark defaults to SPY.",
    ),
    Field(
        "excess_return_20d",
        "Excess Return (1m, vs SPY)",
        "Momentum",
        "technical",
        +1,
        unit="pct",
        description="One-month return less the benchmark's over the same span.",
        coverage_note="Null when the benchmark fund lacks the history; the "
        "benchmark defaults to SPY.",
    ),
    Field(
        "volatility_20",
        "20-Day Volatility",
        "Volatility",
        "technical",
        None,
        unit="pct",
        description="Realized standard deviation of daily returns over 20 "
        "sessions. Strongly persistent, which makes it the most "
        "forecastable quantity here — but whether low or high is "
        "wanted depends on the objective.",
    ),
    Field(
        "atr_pct",
        "ATR %",
        "Volatility",
        "technical",
        None,
        unit="pct",
        description="Average True Range as a fraction of price: typical daily "
        "range, the natural unit for stop placement.",
    ),
    Field(
        "consolidation_tightness",
        "Consolidation Tightness",
        "Volatility",
        "technical",
        -1,
        unit="score",
        description="How tight the recent price base is. Lower means a quieter base.",
    ),
    Field(
        "dollar_volume_20d_avg",
        "Avg Dollar Volume (20d)",
        "Liquidity",
        "technical",
        +1,
        unit="usd",
        description="Mean daily traded value over 20 sessions — the practical "
        "constraint on position size.",
    ),
    Field(
        "volume_ratio",
        "Volume Ratio",
        "Liquidity",
        "technical",
        None,
        description="Current volume against its recent average; unusual "
        "activity in either direction.",
    ),
    Field(
        "close",
        "Close Price",
        "Liquidity",
        "technical",
        None,
        unit="usd",
        rankable=False,
        description="Latest close on or before the signal date. Offered as a "
        "filter — `>= 5` is the conventional penny-stock gate, and "
        "the structural universe has no price floor of its own — but "
        "not for ranking, where a share price says nothing about a "
        "security relative to another.",
    ),
    Field(
        "marketcap",
        "Market Cap",
        "Size",
        "fundamental",
        None,
        unit="usd",
        description="Point-in-time market capitalization from the latest ART "
        "filing available on the signal date. Priced at the filing "
        "date; `marketcap_daily` reprices it at the signal day.",
    ),
    Field(
        "pe",
        "P/E",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Price to earnings. Non-positive is undefined, not cheap: "
        "a loss-maker has no meaningful P/E and is masked from "
        "ranks rather than ranked cheapest. Priced at the filing "
        "date; `pe_daily` reprices it at the signal day.",
    ),
    Field(
        "ps",
        "P/S",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Price to sales. Defined wherever revenue is positive, so "
        "it survives loss-making years that void P/E. Priced at the "
        "filing date; `ps_daily` reprices it at the signal day.",
    ),
    Field(
        "pb",
        "P/B",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Price to book. Negative book value is undefined, and it "
        "understates asset-light firms whose value is intangible. "
        "Priced at the filing date; `pb_daily` reprices it at the "
        "signal day.",
    ),
    Field(
        "evebitda",
        "EV/EBITDA",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Enterprise value to EBITDA — capital-structure neutral, "
        "so it compares across differing leverage. Priced at the "
        "filing date; `evebitda_daily` reprices it at the signal "
        "day.",
    ),
    Field(
        "evebit",
        "EV/EBIT",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Enterprise value to EBIT. Stricter than EV/EBITDA, which "
        "adds depreciation back: for a capital-intensive business "
        "that charge is a real recurring cost, not an accounting "
        "artefact. Priced at the filing date; `evebit_daily` "
        "reprices it at the signal day.",
    ),
    Field(
        "fcf_yield",
        "FCF Yield",
        "Valuation",
        "fundamental",
        +1,
        unit="pct",
        description="Free cash flow over market cap. Harder to manipulate than "
        "earnings-based multiples, and meaningful when negative.",
    ),
    Field(
        "divyield",
        "Dividend Yield",
        "Valuation",
        "fundamental",
        None,
        unit="pct",
        description="Trailing dividend yield. High yield can signal value or "
        "distress, so direction is the caller's.",
    ),
    Field(
        "gross_profitability",
        "Gross Profitability",
        "Profitability",
        "fundamental",
        +1,
        description="Gross profit divided by total assets. Measured this high "
        "on the income statement it is less contaminated by "
        "accounting choices than net income, and predicts returns "
        "about as well as book-to-market.",
        citation="Novy-Marx (2013)",
    ),
    Field(
        "roic",
        "Return on Invested Capital",
        "Profitability",
        "fundamental",
        +1,
        description="Return on capital actually employed in operations — "
        "the cleanest single read on business quality.",
    ),
    Field(
        "roe",
        "Return on Equity",
        "Profitability",
        "fundamental",
        +1,
        description="Net income over shareholders' equity. Inflated by "
        "leverage, so it pairs poorly with debt screens.",
    ),
    Field(
        "roa",
        "Return on Assets",
        "Profitability",
        "fundamental",
        +1,
        description="Net income over total assets; leverage-neutral.",
    ),
    Field(
        "grossmargin",
        "Gross Margin",
        "Profitability",
        "fundamental",
        +1,
        unit="pct",
        description="Gross profit as a share of revenue — pricing "
        "power and cost structure.",
    ),
    Field(
        "netmargin",
        "Net Margin",
        "Profitability",
        "fundamental",
        +1,
        unit="pct",
        description="Net income as a share of revenue.",
    ),
    Field(
        "ebitdamargin",
        "EBITDA Margin",
        "Profitability",
        "fundamental",
        +1,
        unit="pct",
        description="EBITDA over revenue; comparable across tax and "
        "depreciation regimes.",
    ),
    Field(
        "ros",
        "Return on Sales",
        "Profitability",
        "fundamental",
        +1,
        unit="pct",
        description="EBIT over revenue. Sits between EBITDA margin and net "
        "margin: after depreciation, which is a real cost, but "
        "before the interest and tax that leverage and domicile "
        "drive rather than the business does.",
    ),
    Field(
        "cfo_to_assets",
        "Cash Flow to Assets",
        "Profitability",
        "fundamental",
        +1,
        description="Operating cash flow over assets: profitability that "
        "has actually been collected in cash.",
    ),
    Field(
        "netinccmnusd",
        "Net Income (Common, USD)",
        "Profitability",
        "fundamental",
        +1,
        unit="usd",
        rankable=False,
        description="Net income attributable to common shareholders, in USD. "
        "Offered as a filter — `> 0` is the standard profitability "
        "gate — but not for ranking, where an absolute dollar "
        "amount would just rank by company size.",
    ),
    Field(
        "accruals",
        "Accruals",
        "Quality",
        "fundamental",
        -1,
        description="(Net income − operating cash flow) / assets. The wedge "
        "between reported profit and cash. Firms with high "
        "accruals systematically underperform, so lower is "
        "better.",
        citation="Sloan (1996); cash-flow form per Hribar & Collins (2002)",
    ),
    Field(
        "interest_coverage",
        "Interest Coverage",
        "Quality",
        "fundamental",
        +1,
        description="EBIT over interest expense — how comfortably debt "
        "service is met. Negative values are meaningful (a loss "
        "against real interest), so they are not masked.",
    ),
    Field(
        "de",
        "Debt / Equity",
        "Quality",
        "fundamental",
        -1,
        description="Total debt over equity. Balance-sheet risk.",
    ),
    Field(
        "currentratio",
        "Current Ratio",
        "Quality",
        "fundamental",
        +1,
        description="Current assets over current liabilities; near-term solvency.",
    ),
    Field(
        "assetturnover",
        "Asset Turnover",
        "Quality",
        "fundamental",
        +1,
        description="Revenue over assets — how hard the asset base works. The "
        "efficiency half of a margin/turnover decomposition.",
    ),
    Field(
        "payoutratio",
        "Payout Ratio",
        "Quality",
        "fundamental",
        None,
        unit="pct",
        description="Dividends as a share of earnings. Very high payout is "
        "fragile; very low may mean reinvestment or hoarding.",
    ),
    Field(
        "roe_volatility_5y",
        "ROE Volatility (5y)",
        "Quality",
        "fundamental",
        -1,
        description="Standard deviation of ROE across five years — "
        "earnings stability. Stable profitability is a core "
        "component of quality factors.",
        citation="Asness, Frazzini & Pedersen (2019), 'Quality Minus Junk'",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "grossmargin_volatility_5y",
        "Gross Margin Volatility (5y)",
        "Quality",
        "fundamental",
        -1,
        description="Five-year dispersion of gross margin; pricing stability.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "quality_history_observations",
        "Annual Filings in 5y Window",
        "Quality",
        "fundamental",
        None,
        unit="count",
        rankable=False,
        description="How many annual filings the five-year window actually "
        "held. Not a quality signal but the evidence behind one: "
        "every `*_change_5y` and `*_volatility_5y` field is null "
        "below six, so this is what a coverage gate is written on.",
    ),
    Field(
        "complete_multi_year_history",
        "Complete 5y History",
        "Quality",
        "fundamental",
        None,
        rankable=False,
        value_type=bool,
        description="Whether the five-year window was deep enough to trust, "
        "which is `quality_history_observations >= 6` precomputed. "
        "Filter on it to score only securities whose history "
        "features resolved, rather than silently ranking them on "
        "the metrics that happened to survive.",
    ),
    Field(
        "revenue_growth_yoy",
        "Revenue Growth (YoY)",
        "Growth",
        "fundamental",
        +1,
        unit="pct",
        description="Year-over-year revenue change.",
    ),
    Field(
        "eps_growth_yoy",
        "EPS Growth (YoY)",
        "Growth",
        "fundamental",
        +1,
        unit="pct",
        description="Year-over-year earnings-per-share change; share-count "
        "aware, so buybacks flatter it.",
    ),
    Field(
        "opinc_growth_yoy",
        "Operating Income Growth (YoY)",
        "Growth",
        "fundamental",
        +1,
        unit="pct",
        description="Year-over-year operating income change — below revenue, "
        "above financing and tax noise.",
    ),
    Field(
        "grossmargin_change_yoy",
        "Gross Margin Change (YoY)",
        "Growth",
        "fundamental",
        +1,
        unit="pct",
        description="Year-over-year gross margin expansion.",
    ),
    Field(
        "gross_profitability_change_5y",
        "Gross Profitability Trend (5y)",
        "Growth",
        "fundamental",
        +1,
        description="Five-year change in gross profitability: improving "
        "quality rather than a single-period level.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "roa_change_5y",
        "ROA Trend (5y)",
        "Growth",
        "fundamental",
        +1,
        description="Five-year change in return on assets — leverage-neutral "
        "improvement, unlike the ROE trend it parallels.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "roic_change_5y",
        "ROIC Trend (5y)",
        "Growth",
        "fundamental",
        +1,
        description="Five-year change in return on invested capital.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "cfo_to_assets_change_5y",
        "Cash Flow to Assets Trend (5y)",
        "Growth",
        "fundamental",
        +1,
        description="Five-year change in cash-based profitability.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "grossmargin_change_5y",
        "Gross Margin Trend (5y)",
        "Growth",
        "fundamental",
        +1,
        unit="pct",
        description="Five-year gross margin expansion.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "de_change_5y",
        "Debt / Equity Trend (5y)",
        "Growth",
        "fundamental",
        -1,
        description="Five-year change in leverage; rising is worse.",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "net_payout_yield",
        "Net Payout Yield",
        "Capital Discipline",
        "fundamental",
        +1,
        unit="pct",
        description="Dividends plus net buybacks over market cap. Captures "
        "total cash returned, unlike dividend yield alone.",
        citation="Boudoukh et al. (2007)",
    ),
    Field(
        "share_dilution_5y",
        "Share Dilution (5y)",
        "Capital Discipline",
        "fundamental",
        -1,
        unit="pct",
        description="Five-year growth in shares outstanding. Net issuers "
        "underperform net repurchasers; lower is better.",
        citation="Pontiff & Woodgate (2008)",
        coverage_note=_FIVE_YEAR,
    ),
    Field(
        "marketcap_daily",
        "Market Cap (Daily)",
        "Size",
        "fundamental",
        None,
        unit="usd",
        description="Market capitalization at the signal-day price rather than "
        "the filing-day price `marketcap` carries, so a name that "
        "halved since its last 10-Q shows its current size here.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "pe_daily",
        "P/E (Daily)",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Signal-day price against the last filed earnings — unlike "
        "`pe`, whose price is also frozen at the filing date. The "
        "same loss-maker masking applies.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "ps_daily",
        "P/S (Daily)",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Signal-day price against the last filed revenue.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "pb_daily",
        "P/B (Daily)",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Signal-day price against the last filed book value.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "evebit_daily",
        "EV/EBIT (Daily)",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Signal-day enterprise value against the last filed EBIT.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "evebitda_daily",
        "EV/EBITDA (Daily)",
        "Valuation",
        "fundamental",
        -1,
        positive_only=True,
        description="Signal-day enterprise value against the last filed EBITDA.",
        coverage_note=_VENDOR_DAILY,
    ),
    Field(
        "recent_event_codes",
        "Recent Event Codes",
        "Events",
        "event",
        unit="count",
        rankable=False,
        allowed_operators=frozenset(
            {"contains_any", "contains_all", "excludes_any", "is_null", "not_null"}
        ),
        value_type=str,
        description="Deduped Sharadar 8-K event codes filed in the lookback "
        "window. Use with `excludes_any` to drop distress "
        "signals — delisting (31), bankruptcy (13), restatement "
        "(42), late filing (36), material impairment (26).",
    ),
    Field(
        "days_since_last_earnings",
        "Days Since Earnings",
        "Events",
        "event",
        unit="days",
        rankable=False,
        description="Sessions since the last earnings release. Small values "
        "mean the price is still digesting a report.",
    ),
    Field(
        "days_since_last_activist_13d",
        "Days Since 13D Filing",
        "Events",
        "event",
        unit="days",
        rankable=False,
        description="Sessions since the last Schedule 13D activist filing.",
    ),
]

FIELDS: dict[str, Field] = {field.key: field for field in _FIELDS}


def get(key: str) -> Field:
    """Return the registered field named ``key``.

    :raises KeyError: with the key spelled out, which is the error a GUI or an
        agent that invented a field name should see.
    """
    try:
        return FIELDS[key]
    except KeyError:
        raise KeyError(f"unknown field {key!r}; {len(FIELDS)} registered") from None


def unknown(keys) -> list[str]:
    """Return the subset of ``keys`` that is not registered.

    Cheap pre-query validation: no database and no frame required.
    """
    return [key for key in keys if key not in FIELDS]


def rankable() -> dict[str, Field]:
    """Return every field that may be used as a rank metric."""
    return {key: f for key, f in FIELDS.items() if f.rankable}


def filterable() -> dict[str, Field]:
    """Return every field that may be used as a filter condition."""
    return {key: f for key, f in FIELDS.items() if f.filterable}


def by_group() -> dict[str, list[Field]]:
    """Return the fields bucketed by group, in registration order.

    The shape a GUI needs to render grouped controls.
    """
    groups: dict[str, list[Field]] = {}
    for field in _FIELDS:
        groups.setdefault(field.group, []).append(field)
    return groups


def sources(keys) -> set[str]:
    """Return which derive chains ``keys`` requires.

    One or more of "technical", "fundamental", and "event", so a screen computes
    only what it was asked for.
    """
    return {get(key).source for key in keys}


def positive_only(keys) -> tuple[str, ...]:
    """Return the subset of ``keys`` needing non-positive masking before ranking.

    What a caller hands to ``Ranking(positive_only=...)`` instead of a hardcoded
    per-strategy constant.
    """
    return tuple(key for key in keys if get(key).positive_only)
