"""Run every golden query and save the expected answers (human-readable QA artifact).

    python -m eval.build_expected
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent.agent import DEFAULT_DB
from agent.sql_tool import SqlTool

from .compare import norm

HERE = Path(__file__).resolve().parent


def load_golden(path: Path = HERE / "golden_set.yaml") -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def build(sql: SqlTool, golden: list[dict]) -> dict:
    expected = {}
    for q in golden:
        cols, rows = sql.execute(q["golden_sql"])
        assert rows, f"{q['id']}: golden query returned no rows"
        assert all(v is not None for r in rows for v in r), f"{q['id']}: NULL in golden result"
        expected[q["id"]] = {"question": q["question"], "columns": cols,
                             "rows": [[norm(v) for v in r] for r in rows]}
    return expected


def main() -> None:
    expected = build(SqlTool(DEFAULT_DB), load_golden())
    out = HERE / "expected_answers.json"
    out.write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")
    for qid, e in expected.items():
        preview = e["rows"][0] if len(e["rows"]) == 1 else f"{len(e['rows'])} rows"
        print(f"{qid}: {preview}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()