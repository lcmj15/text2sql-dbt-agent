"""
The agent loop (ReAct style: reason -> act with a tool -> observe -> repeat).

    question
       |
       v
    LLM --(tool call)--> run tool --(result)--> LLM --(tool call)--> ...
       |
       +--(text, no tool call)--> final answer + final SQL

Two modes, used by the evaluation:
  * with_docs : tools = [get_dbt_docs, run_sql], prompt WITH_DOCS
  * no_docs   : tools = [run_sql],              prompt NO_DOCS  (schema-only baseline)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import docs_tool, prompts, sql_tool
from .llm import GeminiLLM, LLMTurn, ToolCall

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "warehouse" / "fitloop.duckdb"
DEFAULT_DBT = ROOT / "dbt_project"
MODES = ("with_docs", "no_docs")


@dataclass
class AgentResult:
    question: str
    answer: str
    sql: str | None
    trace: list[dict] = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str | None = None


def extract_sql(text: str) -> str | None:
    blocks = re.findall(r"```sql\s*(.*?)```", text or "", flags=re.S | re.I)
    return blocks[-1].strip() if blocks else None


class Text2SQLAgent:
    def __init__(self, mode: str = "with_docs", db_path: Path = DEFAULT_DB,
                 dbt_dir: Path = DEFAULT_DBT, max_steps: int = 12,
                 llm_factory: Callable[[str, list[dict]], object] | None = None,
                 sql: sql_tool.SqlTool | None = None):
        assert mode in MODES, f"mode must be one of {MODES}"
        self.mode = mode
        self.max_steps = max_steps
        self.sql = sql or sql_tool.SqlTool(db_path)
        self.tools: dict[str, Callable[..., str]] = {"run_sql": lambda query: self.sql(query)}
        specs = [sql_tool.TOOL_SPEC]
        if mode == "with_docs":
            self.docs = docs_tool.DbtDocs(dbt_dir)
            self.tools["get_dbt_docs"] = lambda topic="index": self.docs.get(topic)
            specs = [docs_tool.TOOL_SPEC, sql_tool.TOOL_SPEC]
        system = prompts.WITH_DOCS if mode == "with_docs" else prompts.NO_DOCS
        factory = llm_factory or (lambda s, t: GeminiLLM(s, t))
        self._new_llm = lambda: factory(system, specs)

    def dispatch(self, call: ToolCall) -> str:
        fn = self.tools.get(call.name)
        if fn is None:
            return f"ERROR: unknown tool '{call.name}'. Available: {', '.join(self.tools)}"
        try:
            return fn(**call.args)
        except TypeError as exc:
            return f"ERROR: bad arguments for {call.name}: {exc}"

    def ask(self, question: str, verbose: bool = False) -> AgentResult:
        llm = self._new_llm()  # fresh conversation per question
        result = AgentResult(question=question, answer="", sql=None)
        t0 = time.time()
        last_ok_sql = None
        try:
            turn: LLMTurn = llm.start(question)
            while True:
                result.input_tokens += turn.input_tokens
                result.output_tokens += turn.output_tokens
                if not turn.tool_calls:
                    result.answer = turn.text
                    break
                if result.steps >= self.max_steps:
                    result.error = f"max_steps ({self.max_steps}) reached"
                    break
                outputs = []
                for call in turn.tool_calls:
                    result.steps += 1
                    output = self.dispatch(call)
                    if call.name == "run_sql" and not output.startswith("ERROR"):
                        last_ok_sql = call.args.get("query")
                    result.trace.append({"tool": call.name, "args": call.args,
                                         "output": output[:2000]})
                    if verbose:
                        print(f"\n--> {call.name}({call.args})\n{output[:800]}")
                    outputs.append((call, output))
                turn = llm.send_tool_results(outputs)
        except Exception as exc:  # noqa: BLE001 – record and keep evaluating
            result.error = f"{type(exc).__name__}: {exc}"
        # The graded SQL is the one in the final answer; fall back to the last query that ran.
        result.sql = extract_sql(result.answer) or last_ok_sql
        result.seconds = round(time.time() - t0, 2)
        return result
