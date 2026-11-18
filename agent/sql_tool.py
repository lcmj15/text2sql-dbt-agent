"""
Tool 2 – run_sql: executes a read-only query against the DuckDB warehouse.

Guardrails (defense in depth):
  1. The connection is opened with read_only=True and external access disabled,
     so the database itself refuses writes, file reads and HTTP.
  2. A cheap static check rejects multi-statement input and non-SELECT verbs
     before the query reaches the engine.
  3. A timeout interrupts runaway queries (e.g. accidental cross joins).
  4. Only the first `max_rows` rows go back to the model, so a big result
     does not blow up the context window.

Errors are returned as text instead of raised: the model reads the error
message and fixes its own SQL on the next step (self-correction loop).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable

ALLOWED_START = re.compile(r"^\s*(with|select|describe|show|summarize)\b", re.I)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|copy|attach|detach|pragma|install|load|"
    r"export|import|checkpoint|vacuum|truncate)\b", re.I)


def strip_sql(query: str) -> str:
    query = re.sub(r"--[^\n]*", "", query)
    query = re.sub(r"/\*.*?\*/", "", query, flags=re.S)
    return query.strip().rstrip(";").strip()


def validate(query: str) -> str | None:
    q = strip_sql(query)
    if not q:
        return "empty query"
    if ";" in q:
        return "only one statement per call is allowed"
    if not ALLOWED_START.match(q):
        return "only SELECT / WITH (or DESCRIBE / SHOW) queries are allowed"
    # ignore string literals when looking for forbidden verbs
    if FORBIDDEN.search(re.sub(r"'[^']*'", "''", q)):
        return "query contains a forbidden (write / admin) keyword"
    return None


def duckdb_connect(db_path: str | Path):
    import duckdb  # imported lazily so the rest of the package works without it
    return duckdb.connect(str(db_path), read_only=True,
                          config={"enable_external_access": False})


class SqlTool:
    def __init__(self, db_path: str | Path | None = None, max_rows: int = 50,
                 timeout_s: float = 20.0, connect: Callable[[], Any] | None = None):
        self.conn = connect() if connect else duckdb_connect(db_path)
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def execute(self, query: str) -> tuple[list[str], list[tuple]]:
        """Run a validated query and return (columns, all rows). Raises on error."""
        error = validate(query)
        if error:
            raise ValueError(error)
        timer = None
        if hasattr(self.conn, "interrupt"):
            timer = threading.Timer(self.timeout_s, self.conn.interrupt)
            timer.start()
        try:
            cur = self.conn.execute(strip_sql(query))
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            if timer:
                timer.cancel()
        return columns, rows

    def __call__(self, query: str) -> str:
        """Tool entry point: always returns text for the LLM."""
        try:
            columns, rows = self.execute(query)
        except Exception as exc:  # noqa: BLE001 – the model should see every error
            return f"ERROR: {type(exc).__name__}: {exc}"
        shown = rows[: self.max_rows]
        out = [" | ".join(columns)]
        out += [" | ".join(_fmt(v) for v in row) for row in shown]
        note = f"\n({len(rows)} rows" + (f", showing first {self.max_rows})" if len(rows) > self.max_rows else ")")
        return "\n".join(out) + note


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6g}" if abs(v) < 1 else f"{v:.2f}"
    return "NULL" if v is None else str(v)


TOOL_SPEC = {
    "name": "run_sql",
    "description": (
        "Execute ONE read-only DuckDB SQL query (SELECT / WITH) against the analytics "
        "warehouse and get the result as text (max 50 rows shown). Use fully qualified "
        "names like gold.fct_conversions. On error, read the message and fix the query."
    ),
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A single DuckDB SQL query."}},
        "required": ["query"],
    },
}
