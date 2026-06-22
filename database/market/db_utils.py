from sqlalchemy.dialects.postgresql import insert as pg_insert


def _insert_ignore(table, conn, keys, data_iter):
    table_cols = {c.name for c in table.table.columns}
    valid = [(i, k) for i, k in enumerate(keys) if k in table_cols]
    if not valid:
        return
    indices, cols = zip(*valid)
    rows = [{cols[j]: row[indices[j]] for j in range(len(cols))} for row in data_iter]
    if not rows:
        return
    safe_chunk = max(1, 65000 // len(cols))
    stmt = pg_insert(table.table).on_conflict_do_nothing()
    for i in range(0, len(rows), safe_chunk):
        conn.execute(stmt.values(rows[i:i + safe_chunk]))
