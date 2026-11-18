"""
Evaluation harness: run the golden set through the agent in each mode and
measure execution accuracy.

    python -m eval.evaluate                       # both modes, 1 run each
    python -m eval.evaluate --runs 3              # 3 runs to measure variance
    python -m eval.evaluate --modes with_docs --ids q03 q07

Outputs (in results/<timestamp>/):
  * attempts.jsonl  – one line per (mode, run, question): SQL, status, trace, tokens
  * summary.md      – accuracy by mode, by tag and by question + failure review list
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agent.agent import MODES, ROOT, Text2SQLAgent

from .build_expected import load_golden
from .compare import compare


def grade(agent: Text2SQLAgent, q: dict, golden_rows: list[tuple]) -> dict:
    result = agent.ask(q["question"])
    record = {"id": q["id"], "question": q["question"], "tags": q.get("tags", []),
              "sql": result.sql, "answer": result.answer, "steps": result.steps,
              "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
              "seconds": result.seconds, "trace": result.trace,
              "tools_used": sorted({t["tool"] for t in result.trace})}
    if result.error and not result.sql:
        record.update(status="agent_error", reason=result.error)
    elif not result.sql:
        record.update(status="no_sql", reason="agent returned no SQL")
    else:
        try:
            _, rows = agent.sql.execute(result.sql)
            ok, reason = compare(golden_rows, rows, q.get("order_matters", False))
            record.update(status="correct" if ok else "wrong_result", reason=reason,
                          agent_rows_preview=[list(map(str, r)) for r in rows[:5]])
        except Exception as exc:  # noqa: BLE001
            record.update(status="sql_error", reason=f"{type(exc).__name__}: {exc}")
    return record


def summarize(records: list[dict], golden: list[dict], modes: list[str], runs: int) -> str:
    by_mode = defaultdict(list)
    for r in records:
        by_mode[r["mode"]].append(r)

    def acc(rs):
        return sum(r["status"] == "correct" for r in rs) / len(rs) if rs else 0.0

    lines = [f"# Evaluation summary – {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{len(golden)} questions x {runs} run(s) per mode. Metric: execution accuracy.", "",
             "## Accuracy by mode", "",
             "| mode | accuracy | per-run accuracy | avg tool calls | avg input tokens | avg seconds |",
             "|---|---|---|---|---|---|"]
    for m in modes:
        rs = by_mode[m]
        per_run = [acc([r for r in rs if r["run"] == k]) for k in range(runs)]
        lines.append(
            f"| {m} | **{acc(rs):.0%}** ({sum(r['status'] == 'correct' for r in rs)}/{len(rs)}) | "
            f"{', '.join(f'{x:.0%}' for x in per_run)} | "
            f"{statistics.mean(r['steps'] for r in rs):.1f} | "
            f"{statistics.mean(r['input_tokens'] for r in rs):,.0f} | "
            f"{statistics.mean(r['seconds'] for r in rs):.1f} |")
    if len(modes) == 2:
        delta = acc(by_mode[modes[0]]) - acc(by_mode[modes[1]])
        lines += ["", f"**Lift from metadata: {delta * 100:+.0f} percentage points** "
                      f"({modes[0]} vs {modes[1]})."]

    tags = sorted({t for q in golden for t in q.get("tags", [])})
    lines += ["", "## Accuracy by tag", "", "| tag | n questions | " + " | ".join(modes) + " |",
              "|---|---|" + "---|" * len(modes)]
    for t in tags:
        n = sum(t in q.get("tags", []) for q in golden)
        cells = [f"{acc([r for r in by_mode[m] if t in r['tags']]):.0%}" for m in modes]
        lines.append(f"| {t} | {n} | " + " | ".join(cells) + " |")

    lines += ["", "## By question (correct runs / total runs)", "",
              "| id | question | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]
    for q in golden:
        cells = []
        for m in modes:
            rs = [r for r in by_mode[m] if r["id"] == q["id"]]
            cells.append(f"{sum(r['status'] == 'correct' for r in rs)}/{len(rs)}")
        lines.append(f"| {q['id']} | {q['question']} | " + " | ".join(cells) + " |")

    status_counts = {m: defaultdict(int) for m in modes}
    for r in records:
        status_counts[r["mode"]][r["status"]] += 1
    lines += ["", "## Outcome breakdown", ""]
    for m in modes:
        lines.append(f"- **{m}**: " + ", ".join(f"{k}={v}" for k, v in sorted(status_counts[m].items())))

    lines += ["", "## Failures to review", ""]
    for r in records:
        if r["status"] != "correct":
            lines += [f"### {r['mode']} · run {r['run']} · {r['id']} – {r['status']}",
                      f"Q: {r['question']}  ", f"Reason: {r['reason']}", "",
                      "```sql", (r.get("sql") or "-- none").strip(), "```", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--ids", nargs="*", help="only these question ids")
    parser.add_argument("--sleep", type=float, default=0.0, help="pause between questions (rate limits)")
    args = parser.parse_args()

    golden = [q for q in load_golden() if not args.ids or q["id"] in args.ids]
    out_dir = ROOT / "results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True)

    records = []
    with (out_dir / "attempts.jsonl").open("w", encoding="utf-8") as f:
        for mode in args.modes:
            agent = Text2SQLAgent(mode=mode)
            golden_rows = {q["id"]: agent.sql.execute(q["golden_sql"])[1] for q in golden}
            for run in range(args.runs):
                for q in golden:
                    rec = grade(agent, q, golden_rows[q["id"]]) | {"mode": mode, "run": run}
                    records.append(rec)
                    f.write(json.dumps(rec, default=str) + "\n")
                    f.flush()
                    print(f"[{mode} run{run}] {q['id']} {rec['status']:<12} {rec['reason'][:70]}")
                    time.sleep(args.sleep)

    summary = summarize(records, golden, args.modes, args.runs)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary.split("## Accuracy by tag")[0])
    print(f"Full report: {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()