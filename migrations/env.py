"""Alembic migration environment for QuorumNexus.

The database URL is resolved from the environment via the same helper the
application engine uses (``database.db_connection.get_database_url``), so there
is exactly one source of truth for connection details.

Schema is defined imperatively in the versioned migration scripts (no
SQLAlchemy ORM metadata / autogenerate), because the platform's tables are
created with raw DDL that includes TimescaleDB hypertables and pgvector columns
that autogenerate does not model cleanly.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from database.db_connection import get_database_url

config = context.config
config.set_main_option("sqlalchemy.url", get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (``--sql`` mode)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
