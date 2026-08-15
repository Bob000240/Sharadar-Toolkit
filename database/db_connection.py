"""A single lazily-built SQLAlchemy engine shared by every repository.

The engine is created on first use and reused for the life of the process, so
connection settings live in one place and the pool is not rebuilt per query.
Credentials come from the environment via a .env file.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

_engine = None


def get_connection():
    """Return the shared engine, building it on first call.

    Reads DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, and DB_NAME from the environment,
    falling back to local defaults for everything but the password.
    """
    global _engine
    if _engine is None:
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        dbname = os.getenv("DB_NAME", "sharadar_toolkit")
        _engine = create_engine(
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}",
            pool_size=1,
            max_overflow=5,
        )
    return _engine
