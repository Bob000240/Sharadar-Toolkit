from database.db_connection import get_connection
import pandas as pd

def create_indicators_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS indicators_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            return_1d DOUBLE PRECISION,
            return_5d DOUBLE PRECISION,
            return_20d DOUBLE PRECISION,
            sma_20 DOUBLE PRECISION,
            sma_50 DOUBLE PRECISION,
            rsi_14 DOUBLE PRECISION,
            macd DOUBLE PRECISION,
            macd_signal DOUBLE PRECISION,
            macd_hist DOUBLE PRECISION,
            volatility_20 DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

def drop_indicators_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS indicators_data;")

    conn.commit()
    cur.close()
    conn.close()

def insert_indicators(df):
    df = df.where(pd.notnull(df), None)
    conn = get_connection()
    cur = conn.cursor()

    sql = """
        INSERT INTO indicators_data
        (symbol, date, return_1d, return_5d, return_20d, sma_20, sma_50, rsi_14,
         macd, macd_signal, macd_hist, volatility_20)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date)
        DO UPDATE SET
            return_1d = EXCLUDED.return_1d,
            return_5d = EXCLUDED.return_5d,
            return_20d = EXCLUDED.return_20d,
            sma_20 = EXCLUDED.sma_20,
            sma_50 = EXCLUDED.sma_50,
            rsi_14 = EXCLUDED.rsi_14,
            macd = EXCLUDED.macd,
            macd_signal = EXCLUDED.macd_signal,
            macd_hist = EXCLUDED.macd_hist,
            volatility_20 = EXCLUDED.volatility_20;
    """

    for _, row in df.iterrows():
        cur.execute(sql, (
            row["symbol"],
            row["date"],
            row["return_1d"],
            row["return_5d"],
            row["return_20d"],
            row["sma_20"],
            row["sma_50"],
            row["rsi_14"],
            row["macd"],
            row["macd_signal"],
            row["macd_hist"],
            row["volatility_20"]
        ))

    conn.commit()
    cur.close()
    conn.close()

def get_indicators(symbol, start_date=None, end_date=None):
    conn = get_connection()
    params = [symbol]

    query = """
        SELECT symbol, date, return_1d, return_5d, return_20d, sma_20, sma_50,
               rsi_14, macd, macd_signal, macd_hist, volatility_20
        FROM indicators_data
        WHERE symbol = %s
    """

    if start_date is not None and end_date is not None:
        query += " AND date BETWEEN %s AND %s"
        params.extend([start_date, end_date])
    
    query += " ORDER BY date ASC;"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    return df
