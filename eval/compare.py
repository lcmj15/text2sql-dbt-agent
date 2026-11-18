"""
Execution-accuracy comparison between the agent's result and the golden result.

Comparing SQL *text* is useless (there are many correct ways to write a query),
so we compare the *result sets*, like the Spider / BIRD text-to-SQL benchmarks.

Rules:
  * Same number of rows.
  * Every golden column must match some agent column (names and order are ignored;
    extra agent columns are allowed, e.g. returning the CAC next to the channel).
  * Numbers match within a relative tolerance (default 0.1%).
  * Strings match case-insensitively; dates/timestamps are compared as ISO dates.
  * Row order is ignored unless the question has order_matters: true.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
from decimal import Decimal
from typing import Any

REL_TOL = 1e-3


def norm(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v).strip()
    if s.endswith(" 00:00:00"):
        s = s[:-9]
    try:  # numbers that arrive as text (e.g. DECIMAL rendered as str)
        return float(s)
    except ValueError:
        return s.lower()


def values_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-9)
    return a == b


def _sort_key(row: tuple) -> tuple:
    return tuple((0, "") if v is None else (1, f"{v:.6g}") if isinstance(v, float) else (2, v)
                 for v in row)


def _rows_equal(golden: list[tuple], agent: list[tuple], order_matters: bool) -> bool:
    if not order_matters:
        golden, agent = sorted(golden, key=_sort_key), sorted(agent, key=_sort_key)
    return all(values_equal(g, a) for gr, ar in zip(golden, agent) for g, a in zip(gr, ar))


def compare(golden_rows: list[tuple], agent_rows: list[tuple],
            order_matters: bool = False) -> tuple[bool, str]:
    """Return (match, reason)."""
    g = [tuple(norm(v) for v in r) for r in golden_rows]
    a = [tuple(norm(v) for v in r) for r in agent_rows]
    if len(g) != len(a):
        return False, f"row count {len(a)} != expected {len(g)}"
    if not g:
        return True, "both empty"
    n_g, n_a = len(g[0]), len(a[0])
    if n_a < n_g:
        return False, f"{n_a} columns < expected {n_g}"

    # candidate agent columns for each golden column (same multiset of values)
    g_cols = list(zip(*g))
    a_cols = list(zip(*a))
    candidates = []
    for gc in g_cols:
        gs = sorted(gc, key=lambda v: _sort_key((v,)))
        cands = [i for i, ac in enumerate(a_cols)
                 if all(values_equal(x, y) for x, y in
                        zip(gs, sorted(ac, key=lambda v: _sort_key((v,)))))]
        if not cands:
            return False, f"no agent column matches expected values {list(gc)[:5]}"
        candidates.append(cands)

    # try column mappings until the full rows line up
    for mapping in itertools.islice(itertools.product(*candidates), 500):
        if len(set(mapping)) != len(mapping):
            continue
        projected = [tuple(row[i] for i in mapping) for row in a]
        if _rows_equal(g, projected, order_matters):
            return True, "match"
    return False, "values match per column but rows are paired differently or out of order"
