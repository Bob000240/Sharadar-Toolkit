import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

_engine = None


def get_database_url() -> str:
    """Build the SQLAlchemy URL from the environment.

    Prefers a full ``DATABASE_URL`` if set (normalizing the driver to
    ``psycopg2``); otherwise assembles it from the discrete ``DB_*`` vars.
    This single source of truth is shared by the app engine and Alembic.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "quorum_nexus")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


def get_connection():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            pool_size=5,
            max_overflow=10,
        )
    return _engine
