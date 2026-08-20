-- QuorumNexus data-integrity diagnostics.
--
--     psql "postgresql://$DB_USER@$DB_HOST/$DB_NAME" -f database/diagnostics.sql
--
-- Every check returns the same shape so the output is scannable:
--     check | severity | n | detail
-- n is the offending row count. n = 0 means the check passed.
--
-- Checks are grouped by failure mode, not by table. Note the comments avoid
-- semicolons so the file survives naive statement splitters.

\pset pager off

-- ─────────────────────────────────────────────────────────────────────────────
-- A. PRICE <-> FEATURE CONSISTENCY  (silent corruption)
-- ─────────────────────────────────────────────────────────────────────────────

-- A1. Features computed from prices Sharadar has since re-adjusted. A split
-- rewrites a ticker's whole history, so these rows are present but WRONG and
-- the missing-date scan in daily_update cannot see them.
SELECT 'A1 stale_features' AS check, 'CRITICAL' AS severity, count(*) AS n,
       count(DISTINCT ep.ticker) || ' tickers' AS detail
FROM equity_prices ep
JOIN technical_features tf ON tf.ticker = ep.ticker AND tf.date = ep.date
WHERE ep.close IS DISTINCT FROM tf.close;

-- A2. Price rows with no feature row.
SELECT 'A2 prices_without_features', 'HIGH', count(*),
       count(DISTINCT ep.ticker) || ' tickers'
FROM equity_prices ep
LEFT JOIN technical_features tf ON tf.ticker = ep.ticker AND tf.date = ep.date
WHERE tf.ticker IS NULL;

-- A3. Feature rows whose price row no longer exists.
SELECT 'A3 orphan_features', 'MEDIUM', count(*),
       count(DISTINCT tf.ticker) || ' tickers'
FROM technical_features tf
LEFT JOIN equity_prices ep ON ep.ticker = tf.ticker AND ep.date = tf.date
WHERE ep.ticker IS NULL;

-- A4. Recent price rows with no daily valuation row. DAILY covers fewer
-- tickers than SEP (funds and non-fundamental securities have no row), so
-- this is a coverage gauge rather than a strict zero check.
SELECT 'A4 prices_without_valuation', 'LOW', count(*),
       count(DISTINCT ep.ticker) || ' tickers'
FROM equity_prices ep
LEFT JOIN daily_valuation dv ON dv.ticker = ep.ticker AND dv.date = ep.date
WHERE ep.date > CURRENT_DATE - 30 AND dv.ticker IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. PRICE SANITY  (bad inputs produce confident, wrong signals)
-- ─────────────────────────────────────────────────────────────────────────────

-- B1. Non-positive or missing close. Every pct_change downstream is garbage.
SELECT 'B1 nonpositive_close', 'HIGH', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM equity_prices WHERE close <= 0 OR close IS NULL;

-- B2. OHLC integrity. Close must sit inside the low/high band.
SELECT 'B2 ohlc_violation', 'MEDIUM', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM equity_prices
WHERE high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
  AND (close > high + 1e-6 OR close < low - 1e-6 OR high < low);

-- B3. Bad prints. A 60%+ single-day move that reverses the next day is a data
-- error or a tick-size artifact, never a real move. A correctly applied split
-- leaves NO such spike, because the whole history is re-adjusted together.
WITH d AS (
    SELECT ticker, date, close,
           lag(close)  OVER (PARTITION BY ticker ORDER BY date) AS prev,
           lead(close) OVER (PARTITION BY ticker ORDER BY date) AS next
    FROM equity_prices WHERE close > 0
)
SELECT 'B3 bad_print_suspects', 'HIGH', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM d
WHERE prev > 0 AND next > 0
  AND abs(close / prev - 1) > 0.60
  AND abs(next / close - 1) > 0.60
  AND sign(close / prev - 1) <> sign(next / close - 1);

-- B4. Sub-penny quotes. One tick is a huge percentage move here, so momentum
-- and volatility features are pure noise. Standard guard is a minimum price
-- floor in the eligibility query, which does not currently have one.
SELECT 'B4 subpenny_rows', 'MEDIUM', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM equity_prices WHERE close > 0 AND close < 0.01;

-- B5. Zero-volume sessions. Legitimate for halts and illiquid names, but they
-- drag the 20-session median dollar volume used by the liquidity floor.
SELECT 'B5 zero_volume_days', 'LOW', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM equity_prices WHERE volume = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- C. POINT-IN-TIME SAFETY  (look-ahead leaks)
-- ─────────────────────────────────────────────────────────────────────────────

-- C1. THE TRAP. For MR* dimensions Sharadar sets datekey = reportperiod, not
-- the filing date, so `datekey <= as_of` admits them on the period-end date --
-- weeks before anyone could have seen the filing -- AND the figures are
-- restated. A PIT filter on datekey does NOT make MR* safe. Any query that
-- forgets `dimension IN ('ARQ','ART','ARY')` leaks silently.
SELECT 'C1 mr_rows_look_pit_safe', 'CRITICAL', count(*),
       'MR* rows whose datekey is a period end, not a filing date'
FROM fundamentals
WHERE dimension IN ('MRQ','MRT','MRY') AND datekey = reportperiod;

-- C2. Fundamentals with NULL datekey. Invisible to PIT queries, still present
-- for anything that naively joins on calendardate.
SELECT 'C2 fundamentals_null_datekey', 'CRITICAL', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM fundamentals WHERE datekey IS NULL;

-- C3. datekey in the future, which would surface a filing before it was filed.
SELECT 'C3 fundamentals_future_datekey', 'CRITICAL', count(*),
       coalesce(max(datekey)::text, '-')
FROM fundamentals WHERE datekey > CURRENT_DATE;

-- C4. AR* rows whose datekey precedes the period end. For AR* this IS a
-- problem. For MR* it is just the datekey = reportperiod convention above, so
-- MR* is excluded here to keep the signal clean.
SELECT 'C4 as_reported_datekey_precedes_period', 'HIGH', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM fundamentals
WHERE dimension IN ('ARQ','ART','ARY')
  AND datekey IS NOT NULL AND reportperiod IS NOT NULL
  AND datekey < reportperiod;

-- C5. Insider rows whose transaction is dated after their own filing.
SELECT 'C5 insider_txn_after_filing', 'MEDIUM', count(*),
       count(DISTINCT ticker) || ' tickers'
FROM insider_transactions
WHERE transactiondate IS NOT NULL AND filingdate IS NOT NULL
  AND transactiondate > filingdate;

-- C6. Sector labels are a CURRENT-STATE snapshot with no history, so sector
-- ranks carry look-ahead. The leak is structural and cannot be detected from
-- inside the table. This only counts how much of the universe is labelled.
SELECT 'C6 tickers_missing_sector', 'HIGH', count(*),
       'of ' || (SELECT count(*) FROM tickers WHERE table_code = 'SEP') || ' SEP rows'
FROM tickers WHERE table_code = 'SEP' AND (sector IS NULL OR sector = '');

-- ─────────────────────────────────────────────────────────────────────────────
-- D. REFERENTIAL GAPS  (joins that silently drop rows)
-- ─────────────────────────────────────────────────────────────────────────────

-- D1. Traded tickers with no descriptor row. Eligibility starts FROM tickers,
-- so these can never be selected no matter how they score.
SELECT 'D1 prices_without_descriptor', 'HIGH', count(*), 'distinct tickers'
FROM (SELECT DISTINCT ep.ticker FROM equity_prices ep
      LEFT JOIN tickers t ON t.ticker = ep.ticker AND t.table_code = 'SEP'
      WHERE t.ticker IS NULL) x;

-- D2. Sector ETFs with no descriptor row. load_data filters TICKERS to
-- table_code='SEP', so only daily_update ever creates these.
SELECT 'D2 etf_missing_descriptor', 'MEDIUM', count(*), string_agg(s.sym, ',')
FROM (VALUES ('SPY'),('XLK'),('XLY'),('XLC'),('XLF'),('XLV'),
             ('XLI'),('XLE'),('XLB'),('XLRE'),('XLU'),('XLP')) AS s(sym)
LEFT JOIN tickers t ON t.ticker = s.sym AND t.table_code = 'SFP'
WHERE t.ticker IS NULL;

-- D3. Sector ETFs with no price history.
SELECT 'D3 etf_missing_prices', 'HIGH', count(*), string_agg(s.sym, ',')
FROM (VALUES ('SPY'),('XLK'),('XLY'),('XLC'),('XLF'),('XLV'),
             ('XLI'),('XLE'),('XLB'),('XLRE'),('XLU'),('XLP')) AS s(sym)
LEFT JOIN (SELECT DISTINCT ticker FROM fund_prices) f ON f.ticker = s.sym
WHERE f.ticker IS NULL;

-- D4. Sector values that ETF_SECTOR_MAP does not cover, so those names can
-- never be matched to a sector benchmark.
SELECT 'D4 sector_without_etf', 'MEDIUM', count(DISTINCT sector),
       coalesce(string_agg(DISTINCT sector, ' | '), '-')
FROM tickers
WHERE table_code = 'SEP' AND sector IS NOT NULL AND sector <> ''
  AND sector NOT IN ('Technology','Consumer Cyclical','Communication Services',
                     'Financial Services','Healthcare','Industrials','Energy',
                     'Basic Materials','Real Estate','Utilities','Consumer Defensive');

-- ─────────────────────────────────────────────────────────────────────────────
-- E. FRESHNESS AND HISTORY HOLES
-- ─────────────────────────────────────────────────────────────────────────────

-- E1. Per-source staleness. A source lagging the others means its updater
-- skipped a window. The three window-based updaters (insider, events,
-- institutional) lose data permanently across a gap, so watch these.
SELECT 'E1 staleness: ' || src,
       CASE WHEN CURRENT_DATE - mx > 10 THEN 'HIGH' ELSE 'OK' END,
       CURRENT_DATE - mx, mx::text
FROM (
    SELECT 'equity_prices' src, max(date) mx FROM equity_prices
    UNION ALL SELECT 'fund_prices', max(date) FROM fund_prices
    UNION ALL SELECT 'technical_features', max(date) FROM technical_features
    UNION ALL SELECT 'daily_valuation', max(date) FROM daily_valuation
    UNION ALL SELECT 'fundamentals(datekey)', max(datekey) FROM fundamentals
    UNION ALL SELECT 'insider(filingdate)', max(filingdate) FROM insider_transactions
    UNION ALL SELECT 'events', max(date) FROM events
    UNION ALL SELECT 'institutional', max(date) FROM institutional_ownership
    UNION ALL SELECT 'macro', max(date) FROM macro
) s ORDER BY 3 DESC;

-- E2. SF3A quarterly holes. SF3 v1 thinned pre-2022 history to one quarter per
-- year; v3 restored it, so a year short of four quarters now means an
-- incomplete load rather than a known vendor gap.
SELECT 'E2 sf3a_quarters_' || yr, 'MEDIUM', q, 'quarters present'
FROM (SELECT extract(year FROM date)::int yr,
             count(DISTINCT date) q
      FROM institutional_ownership GROUP BY 1) x
WHERE q < 4 ORDER BY yr;

-- E3. Macro columns that are entirely NULL, meaning a FRED series never loaded.
SELECT 'E3 macro_dead_series', 'MEDIUM', count(*), coalesce(string_agg(col, ','), '-')
FROM (
    SELECT a.attname AS col
    FROM pg_attribute a
    WHERE a.attrelid = 'macro'::regclass AND a.attnum > 0 AND NOT a.attisdropped
      AND a.attname <> 'date'
) c
WHERE (SELECT count(*) FROM macro m
       WHERE (to_jsonb(m) ->> c.col) IS NOT NULL) = 0;

-- E4. Fundamentals dimension freshness. daily_update used to refresh only
-- ARY/ARQ/ART, which left MR* stamped at whatever the last bulk load wrote.
SELECT 'E4 dim_' || dimension,
       CASE WHEN max(lastupdated) < (SELECT max(lastupdated) FROM fundamentals) - 30
            THEN 'STALE' ELSE 'OK' END,
       count(*), 'last stamped ' || max(lastupdated)::text
FROM fundamentals GROUP BY dimension ORDER BY dimension;
