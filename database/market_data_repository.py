from database.db_connection import get_connection
from data_collection.market_data import MarketData
import pandas as pd

def create_OHLCV_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS OHLCV_data (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            PRIMARY KEY (symbol, date)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    
def drop_OHLCV_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS OHLCV_data;")

    conn.commit()
    cur.close()
    conn.close()

def insert_OHLCV_table(df):
    conn = get_connection()
    cur = conn.cursor()
    query  = """INSERT INTO OHLCV_data (symbol, date, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, date) DO NOTHING;"""

    for _, row in df.iterrows():
        cur.execute(query, 
                    (row['symbol'], 
                     row['date'], 
                     row['open'], 
                     row['high'], 
                     row['low'], 
                     row['close'], 
                     row['volume']))

    conn.commit()
    cur.close()
    conn.close()


def get_OHLCV(symbol, start_date=None, end_date=None):
    conn = get_connection()
    query = """SELECT symbol, date, open, high, low, close, volume
        FROM OHLCV_data 
        WHERE symbol = %s"""

    if start_date is not None and end_date is not None:
        query = """
            SELECT symbol, date, open, high, low, close, volume
            FROM OHLCV_data
            WHERE symbol = %s
              AND date BETWEEN %s AND %s
            ORDER BY date ASC;
        """
        params = (symbol, start_date, end_date)
    else:
        query = """
            SELECT symbol, date, open, high, low, close, volume
            FROM OHLCV_data
            WHERE symbol = %s
            ORDER BY date ASC;
        """
        params = (symbol,)

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    return df