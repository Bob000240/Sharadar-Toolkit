"""
Fast bulk insert via Postgres COPY (for large initial/refresh loads).

Streams a DataFrame into a TEMP staging table with COPY, then
INSERT ... SELECT ... ON CONFLICT into the real target. Far faster than
row-by-row executemany. Reuses a repo's column list as the schema-of-record;
small/incremental writes still use repo.insert() (which also does the
restatement-aware DO UPDATE for fundamentals/macro).
"""

from __future__ import annotations
import io

import pandas as pd

from database.db_connection import get_connection


def copy_insert(
    table: str,
    columns: list[str],
    df: pd.DataFrame,
    conflict: str = "ON CONFLICT DO NOTHING",
) -> int:
    """COPY df[columns] into `table` via a temp staging table. Returns rows inserted.

    NaN/NaT become SQL NULL. Extra df columns are ignored; column order follows
    `columns`. `conflict` is appended to the final INSERT (default: skip dupes).
    """
    if df.empty:
        return 0

    frame = df[columns]
    collist = ", ".join(columns)
    buf = io.StringIO()
    frame.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)

    raw = get_connection().raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"DROP TABLE IF EXISTS _bulk_stg")
        cur.execute(f"CREATE TEMP TABLE _bulk_stg (LIKE {table}) ON COMMIT DROP")
        cur.copy_expert(
            f"COPY _bulk_stg ({collist}) FROM STDIN WITH (FORMAT csv, NULL '')", buf
        )
        cur.execute(
            f"INSERT INTO {table} ({collist}) "
            f"SELECT {collist} FROM _bulk_stg {conflict}"
        )
        inserted = cur.rowcount
        raw.commit()
        return inserted
    finally:
        raw.close()
