"""
Offline tests: no API key, no DuckDB, no dbt needed.  Run with:  pytest -q

They check the parts that must be right *before* spending money on LLM calls:
the golden set, the grader, the SQL guardrails, the docs tool and the agent loop.
"""
from pathlib import Path

import pytest

from agent import docs_tool, sql_tool
from agent.agent import Text2SQLAgent, extract_sql
from agent.llm import LLMTurn, ToolCall
from eval.build_expected import build, load_golden
from eval.compare import compare
from eval.evaluate import grade

from . import sqlite_mirror

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sql():
    conn = sqlite_mirror.build()
    return sql_tool.SqlTool(connect=lambda: conn)


@pytest.fixture(scope="module")
def golden():
    return load_golden()


# ------------------------------------------------------------------ golden set
def test_golden_set_size_and_ids(golden):
    assert 15 <= len(golden) <= 20
    assert len({q["id"] for q in golden}) == len(golden)


def test_every_golden_query_runs_and_is_non_empty(sql, golden):
    expected = build(sql, golden)
    assert len(expected) == len(golden)


def test_traps_actually_change_the_answer(sql):
    """If the business rules did not change any number, the experiment would be pointless."""
    _, right = sql.execute("""select count(*) from gold.fct_conversions f
        left join gold.dim_campaigns c using (campaign_id)
        where f.conversion_type = 'paid_subscription' and coalesce(c.is_internal, false) = false""")
    _, naive_all_events = sql.execute("select count(*) from gold.fct_conversions")
    _, naive_inner_join = sql.execute("""select count(*) from gold.fct_conversions f
        join gold.dim_campaigns c using (campaign_id)
        where f.conversion_type = 'paid_subscription' and not c.is_internal""")
    _, naive_no_qa_filter = sql.execute(
        "select count(*) from gold.fct_conversions where conversion_type = 'paid_subscription'")
    assert len({right[0][0], naive_all_events[0][0], naive_inner_join[0][0],
                naive_no_qa_filter[0][0]}) == 4


# --------------------------------------------------------------------- grader
def test_compare_ignores_names_order_and_extra_columns():
    golden = [("paid_search", 50.0), ("display", 80.0)]
    agent = [(80.00001, "DISPLAY", 123), (50.0, "paid_search", 456)]
    assert compare(golden, agent)[0]


def test_compare_respects_order_when_required():
    golden = [("a", 1.0), ("b", 2.0)]
    assert not compare(golden, [("b", 2.0), ("a", 1.0)], order_matters=True)[0]
    assert compare(golden, [("b", 2.0), ("a", 1.0)], order_matters=False)[0]


def test_compare_rejects_wrong_values_and_row_counts():
    assert not compare([(100.0,)], [(101.0,)])[0]
    assert not compare([("x",)], [("x",), ("y",)])[0]
    assert not compare([("a", 1.0), ("b", 2.0)], [("a", 2.0), ("b", 1.0)])[0]  # mispaired


def test_golden_matches_itself(sql, golden):
    for q in golden:
        _, rows = sql.execute(q["golden_sql"])
        assert compare(rows, rows, q.get("order_matters", False))[0], q["id"]


# ----------------------------------------------------------------- SQL tool
@pytest.mark.parametrize("bad", [
    "drop table gold.dim_campaigns",
    "select 1; delete from gold.fct_conversions",
    "insert into x values (1)",
    "copy gold.dim_campaigns to 'out.csv'",
    "attach 'other.db'",
])
def test_sql_guardrails_block_writes(bad):
    assert sql_tool.validate(bad) is not None


def test_sql_guardrails_allow_reads():
    assert sql_tool.validate("with x as (select 1) select * from x;") is None
    assert sql_tool.validate("select 'please update me' as txt") is None  # keyword inside a string


def test_sql_tool_returns_errors_as_text(sql):
    assert sql("select * from gold.does_not_exist").startswith("ERROR")


# ---------------------------------------------------------------- docs tool
def test_docs_tool_yaml_fallback():
    docs = docs_tool.DbtDocs(ROOT / "dbt_project")
    assert set(docs.models) == {"dim_campaigns", "fct_ad_performance_daily", "fct_conversions"}
    assert {"business_glossary", "business_rules", "metric_definitions"} <= set(docs.doc_blocks)
    assert "paid_subscription" in docs.get("fct_conversions")
    assert "Accepted values" in docs.get("dim_campaigns")
    assert docs.get("nope").startswith("ERROR")


# --------------------------------------------------------------- agent loop
class ScriptedLLM:
    """Fake model: replays a fixed list of turns. Lets us test the loop with no API."""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.received = []

    def start(self, question):
        return next(self.turns)

    def send_tool_results(self, results):
        self.received.append(results)
        return next(self.turns)


def test_agent_loop_with_fake_model(sql, golden):
    q = next(x for x in golden if x["id"] == "q03")
    script = [
        LLMTurn(tool_calls=[ToolCall("get_dbt_docs", {"topic": "index"})]),
        LLMTurn(tool_calls=[ToolCall("get_dbt_docs", {"topic": "business_rules"}),
                            ToolCall("run_sql", {"query": "select count(*) from gold.typo"})]),
        LLMTurn(tool_calls=[ToolCall("run_sql", {"query": q["golden_sql"]})]),
        LLMTurn(text=f"We had N conversions.\n```sql\n{q['golden_sql']}```"),
    ]
    fake = ScriptedLLM(script)
    agent = Text2SQLAgent(mode="with_docs", sql=sql, llm_factory=lambda s, t: fake)
    _, golden_rows = sql.execute(q["golden_sql"])
    rec = grade(agent, q, golden_rows)
    assert rec["status"] == "correct", rec
    assert rec["steps"] == 4
    assert fake.received[1][1][1].startswith("ERROR")  # the model saw the SQL error


def test_no_docs_mode_has_no_docs_tool(sql):
    fake = ScriptedLLM([LLMTurn(tool_calls=[ToolCall("get_dbt_docs", {"topic": "index"})]),
                        LLMTurn(text="done")])
    agent = Text2SQLAgent(mode="no_docs", sql=sql, llm_factory=lambda s, t: fake)
    result = agent.ask("anything")
    assert "unknown tool" in result.trace[0]["output"]


def test_max_steps_guard(sql):
    loop = [LLMTurn(tool_calls=[ToolCall("run_sql", {"query": "select 1"})])] * 20
    agent = Text2SQLAgent(mode="no_docs", sql=sql, max_steps=3,
                          llm_factory=lambda s, t: ScriptedLLM(loop))
    result = agent.ask("loop forever")
    assert result.error and result.steps == 3
    assert result.sql == "select 1"  # falls back to the last successful query


def test_extract_sql_takes_last_block():
    assert extract_sql("```sql\nselect 1\n```\n then\n```SQL\nselect 2\n```") == "select 2"
