"""SQLite warehouse access: connection, schema init, fast bulk load, query helpers."""

from __future__ import annotations

import glob
import sqlite3
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from networkanalysis.paths import WAREHOUSE_DB

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path | None = None, *, fast: bool = False) -> sqlite3.Connection:
    path = Path(db_path or WAREHOUSE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA temp_store=MEMORY")
    if fast:
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("PRAGMA cache_size=-200000")
    return con


def init_db(db_path: str | Path | None = None) -> None:
    con = connect(db_path)
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        con.close()


# the job table must survive a regeneration - the in-flight generate job polls its own
# row for progress, and dropping it mid-run freezes the dashboard's progress bar
_KEEP_ON_RESET = {"job"}


def reset_db(db_path: str | Path | None = None) -> None:
    """Clear all data tables and recreate the schema, keeping the same file (so other open
    connections - e.g. the API - are not invalidated) and preserving the ``job`` table."""
    path = Path(db_path or WAREHOUSE_DB)
    if not path.exists():
        init_db(path)
        return
    con = connect(path, fast=True)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        con.execute("BEGIN")
        for n in names:
            if n not in _KEEP_ON_RESET:
                con.execute(f"DROP TABLE IF EXISTS {n}")
        con.execute("COMMIT")
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        con.execute("VACUUM")
    finally:
        con.close()


def _prep_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def insert_dataframe(
    con: sqlite3.Connection, table: str, df: pd.DataFrame, *, chunksize: int = 100_000
) -> int:
    if df.empty:
        return 0
    df = _prep_frame(df)
    cols = list(df.columns)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    total = 0
    con.execute("BEGIN")
    try:
        for start in range(0, len(df), chunksize):
            block = df.iloc[start : start + chunksize]
            rows = list(map(tuple, block.to_numpy(dtype=object)))
            con.executemany(sql, rows)
            total += len(rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return total


def load_parquet_glob(
    con: sqlite3.Connection, table: str, pattern: str | Iterable[str], *, progress=None
) -> int:
    import pyarrow.parquet as pq

    files = sorted(glob.glob(pattern)) if isinstance(pattern, str) else sorted(pattern)
    total = 0
    for i, f in enumerate(files):
        df = pq.read_table(f).to_pandas()
        total += insert_dataframe(con, table, df)
        if progress:
            progress(f, i + 1, len(files))
    return total


def query_df(sql: str, params: tuple | dict | None = None, db_path: str | Path | None = None) -> pd.DataFrame:
    con = connect(db_path)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def table_counts(db_path: str | Path | None = None) -> dict[str, int]:
    con = connect(db_path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        out = {}
        for n in names:
            try:
                out[n] = con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
            except sqlite3.Error:
                out[n] = -1
        return out
    finally:
        con.close()
