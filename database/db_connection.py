import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

_engine = None


def get_connection():
    global _engine
    if _engine is None:
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        dbname = os.getenv("DB_NAME", "quorum_nexus")
        _engine = create_engine(
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}",
            pool_size=5,
            max_overflow=10,
        )
    return _engine
