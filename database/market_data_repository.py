from database.db_connection import get_connection
from data_collection.market_data import MarketData


def create_OHLCV_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        DROP TABLE IF EXISTS OHLCV_data;
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

if __name__ == "__main__":
    data = MarketData()
    df = data.get_OHLCV("AAPL", "2023-01-01", "2023-12-31")

    create_OHLCV_table()
    insert_OHLCV_table(df)  