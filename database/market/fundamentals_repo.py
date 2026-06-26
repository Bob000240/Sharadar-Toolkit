from database.db_connection import get_connection
import pandas as pd
from sqlalchemy import text

_COLUMNS = [
    "ticker",
    "dimension",
    "calendardate",
    "datekey",
    "reportperiod",
    "fiscalperiod",
    "lastupdated",
    "accoci",
    "assets",
    "assetsavg",
    "assetsc",
    "assetsnc",
    "assetturnover",
    "bvps",
    "capex",
    "cashneq",
    "cashnequsd",
    "consolinc",
    "cor",
    "currentratio",
    "de",
    "debt",
    "debtc",
    "debtnc",
    "debtusd",
    "deferredrev",
    "depamor",
    "deposits",
    "divyield",
    "dps",
    "ebit",
    "ebitda",
    "ebitdamargin",
    "ebitdausd",
    "ebitusd",
    "ebt",
    "eps",
    "epsdil",
    "epsusd",
    "equity",
    "equityavg",
    "equityusd",
    "ev",
    "evebit",
    "evebitda",
    "fcf",
    "fcfps",
    "fxusd",
    "gp",
    "grossmargin",
    "intangibles",
    "intexp",
    "invcap",
    "invcapavg",
    "inventory",
    "investments",
    "investmentsc",
    "investmentsnc",
    "liabilities",
    "liabilitiesc",
    "liabilitiesnc",
    "marketcap",
    "ncf",
    "ncfbus",
    "ncfcommon",
    "ncfdebt",
    "ncfdiv",
    "ncff",
    "ncfi",
    "ncfinv",
    "ncfo",
    "ncfx",
    "netinc",
    "netinccmn",
    "netinccmnusd",
    "netincdis",
    "netincnci",
    "netmargin",
    "opex",
    "opinc",
    "payables",
    "payoutratio",
    "pb",
    "pe",
    "pe1",
    "ppnenet",
    "prefdivis",
    "price",
    "ps",
    "ps1",
    "receivables",
    "retearn",
    "revenue",
    "revenueusd",
    "rnd",
    "roa",
    "roe",
    "roic",
    "ros",
    "sbcomp",
    "sgna",
    "sharefactor",
    "sharesbas",
    "shareswa",
    "shareswadil",
    "sps",
    "tangibles",
    "taxassets",
    "taxexp",
    "taxliabilities",
    "tbvps",
    "workingcapital",
]
_COL_LIST = ", ".join(_COLUMNS)
_BIND_LIST = ", ".join(f":{c}" for c in _COLUMNS)


def create_table():
    with get_connection().begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker          TEXT    NOT NULL,
                dimension       TEXT    NOT NULL,
                calendardate    DATE,
                datekey         DATE    NOT NULL,
                reportperiod    DATE,
                fiscalperiod    TEXT,
                lastupdated     DATE,

                accoci          DOUBLE PRECISION,
                assets          DOUBLE PRECISION,
                assetsavg       DOUBLE PRECISION,
                assetsc         DOUBLE PRECISION,
                assetsnc        DOUBLE PRECISION,
                assetturnover   DOUBLE PRECISION,
                bvps            DOUBLE PRECISION,
                capex           DOUBLE PRECISION,
                cashneq         DOUBLE PRECISION,
                cashnequsd      DOUBLE PRECISION,
                cor             DOUBLE PRECISION,
                consolinc       DOUBLE PRECISION,
                currentratio    DOUBLE PRECISION,
                de              DOUBLE PRECISION,
                debt            DOUBLE PRECISION,
                debtc           DOUBLE PRECISION,
                debtnc          DOUBLE PRECISION,
                debtusd         DOUBLE PRECISION,
                deferredrev     DOUBLE PRECISION,
                depamor         DOUBLE PRECISION,
                deposits        DOUBLE PRECISION,
                divyield        DOUBLE PRECISION,
                dps             DOUBLE PRECISION,
                ebit            DOUBLE PRECISION,
                ebitda          DOUBLE PRECISION,
                ebitdamargin    DOUBLE PRECISION,
                ebitdausd       DOUBLE PRECISION,
                ebitusd         DOUBLE PRECISION,
                ebt             DOUBLE PRECISION,
                eps             DOUBLE PRECISION,
                epsdil          DOUBLE PRECISION,
                epsusd          DOUBLE PRECISION,
                equity          DOUBLE PRECISION,
                equityavg       DOUBLE PRECISION,
                equityusd       DOUBLE PRECISION,
                ev              DOUBLE PRECISION,
                evebit          DOUBLE PRECISION,
                evebitda        DOUBLE PRECISION,
                fcf             DOUBLE PRECISION,
                fcfps           DOUBLE PRECISION,
                fxusd           DOUBLE PRECISION,
                gp              DOUBLE PRECISION,
                grossmargin     DOUBLE PRECISION,
                intangibles     DOUBLE PRECISION,
                intexp          DOUBLE PRECISION,
                invcap          DOUBLE PRECISION,
                invcapavg       DOUBLE PRECISION,
                inventory       DOUBLE PRECISION,
                investments     DOUBLE PRECISION,
                investmentsc    DOUBLE PRECISION,
                investmentsnc   DOUBLE PRECISION,
                liabilities     DOUBLE PRECISION,
                liabilitiesc    DOUBLE PRECISION,
                liabilitiesnc   DOUBLE PRECISION,
                marketcap       DOUBLE PRECISION,
                ncf             DOUBLE PRECISION,
                ncfbus          DOUBLE PRECISION,
                ncfcommon       DOUBLE PRECISION,
                ncfdebt         DOUBLE PRECISION,
                ncfdiv          DOUBLE PRECISION,
                ncff            DOUBLE PRECISION,
                ncfi            DOUBLE PRECISION,
                ncfinv          DOUBLE PRECISION,
                ncfo            DOUBLE PRECISION,
                ncfx            DOUBLE PRECISION,
                netinc          DOUBLE PRECISION,
                netinccmn       DOUBLE PRECISION,
                netinccmnusd    DOUBLE PRECISION,
                netincdis       DOUBLE PRECISION,
                netincnci       DOUBLE PRECISION,
                netmargin       DOUBLE PRECISION,
                opex            DOUBLE PRECISION,
                opinc           DOUBLE PRECISION,
                payables        DOUBLE PRECISION,
                payoutratio     DOUBLE PRECISION,
                pb              DOUBLE PRECISION,
                pe              DOUBLE PRECISION,
                pe1             DOUBLE PRECISION,
                ppnenet         DOUBLE PRECISION,
                prefdivis       DOUBLE PRECISION,
                price           DOUBLE PRECISION,
                ps              DOUBLE PRECISION,
                ps1             DOUBLE PRECISION,
                receivables     DOUBLE PRECISION,
                retearn         DOUBLE PRECISION,
                revenue         DOUBLE PRECISION,
                revenueusd      DOUBLE PRECISION,
                rnd             DOUBLE PRECISION,
                roa             DOUBLE PRECISION,
                roe             DOUBLE PRECISION,
                roic            DOUBLE PRECISION,
                ros             DOUBLE PRECISION,
                sbcomp          DOUBLE PRECISION,
                sgna            DOUBLE PRECISION,
                sharefactor     DOUBLE PRECISION,
                sharesbas       DOUBLE PRECISION,
                shareswa        DOUBLE PRECISION,
                shareswadil     DOUBLE PRECISION,
                sps             DOUBLE PRECISION,
                tangibles       DOUBLE PRECISION,
                taxassets       DOUBLE PRECISION,
                taxexp          DOUBLE PRECISION,
                taxliabilities  DOUBLE PRECISION,
                tbvps           DOUBLE PRECISION,
                workingcapital  DOUBLE PRECISION,

                PRIMARY KEY (ticker, dimension, datekey)
            );
            CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals (ticker);
            CREATE INDEX IF NOT EXISTS idx_fundamentals_date ON fundamentals (calendardate);
        """)
        )


def drop_table():
    with get_connection().begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fundamentals CASCADE"))


_NON_PK = [c for c in _COLUMNS if c not in ("ticker", "dimension", "datekey")]
_UPDATE_SET = ", ".join(f"{c}=EXCLUDED.{c}" for c in _NON_PK)


def insert(df: pd.DataFrame):
    if df.empty:
        return
    records = (
        df[_COLUMNS].where(pd.notnull(df[_COLUMNS]), None).to_dict(orient="records")
    )
    records = [{k: None if v is pd.NaT else v for k, v in r.items()} for r in records]
    with get_connection().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO fundamentals ({_COL_LIST}) VALUES ({_BIND_LIST}) "
                f"ON CONFLICT (ticker, dimension, datekey) DO UPDATE SET {_UPDATE_SET}"
            ),
            records,
        )


def get(
    tickers: str | list[str] | None = None,
    dimension: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    q = "SELECT * FROM fundamentals WHERE TRUE"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " AND ticker = ANY(:tickers)"
    if dimension is not None:
        params["dim"] = dimension
        q += " AND dimension = :dim"
    if start_date is not None:
        params["start"] = start_date
        q += " AND calendardate >= :start"
    if end_date is not None:
        params["end"] = end_date
        q += " AND calendardate <= :end"
    q += " ORDER BY ticker, dimension, datekey"
    return pd.read_sql_query(text(q), get_connection(), params=params)


def get_latest(
    tickers: str | list[str] | None, dimension: str, signal_day: pd.Timestamp
) -> pd.DataFrame:
    params = {
        "dim": dimension,
        "signal_day": signal_day.date() if hasattr(signal_day, "date") else signal_day,
    }
    ticker_clause = ""
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        ticker_clause = "AND ticker = ANY(:tickers)"
    q = text(f"""
        SELECT DISTINCT ON (ticker) *
        FROM fundamentals
        WHERE TRUE
          {ticker_clause}
          AND dimension = :dim
          AND datekey <= :signal_day
        ORDER BY ticker, datekey DESC
    """)
    return pd.read_sql_query(q, get_connection(), params=params)


def get_latest_date(tickers: str | list[str] | None = None) -> pd.DataFrame:
    q = "SELECT ticker, MAX(datekey) AS latest_date FROM fundamentals"
    params = {}
    if tickers is not None:
        params["tickers"] = [tickers] if isinstance(tickers, str) else tickers
        q += " WHERE ticker = ANY(:tickers)"
    q += " GROUP BY ticker"
    return pd.read_sql_query(text(q), get_connection(), params=params)
