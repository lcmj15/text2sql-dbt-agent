# Text-to-SQL agent grounded in dbt metadata

A small, fully reproducible project that answers marketing questions in plain English
by writing and running SQL, and **measures how much semantic metadata (dbt docs,
business glossary, business rules) improves its accuracy**.

```
"What was the CAC of each paid media channel in H1 2025?"
        │
        ▼
 ┌──────────────┐  get_dbt_docs("index" | model | page)   ┌────────────────────────┐
 │ Gemini agent │ ───────────────────────────────────────▶│ dbt manifest / catalog │
 │ (tool loop)  │                                         └────────────────────────┘
 │              │  run_sql("select ...")  (read-only)     ┌────────────────────────┐
 │              │ ───────────────────────────────────────▶│ DuckDB warehouse (gold)│
 └──────────────┘                                         └────────────────────────┘
        │
        ▼
 answer + final SQL  ──▶  eval harness: run SQL, compare result with golden result
```

## Why

Text-to-SQL demos usually work on clean schemas where column names say everything.
Real warehouses don't: "conversion" means a paid subscription, not a signup; QA
campaigns must be excluded; organic traffic disappears with the wrong join. That
knowledge lives in the analytics engineer's head, or, ideally, in dbt docs.

This project treats that metadata as **agent context** and runs a controlled experiment:
same model, same SQL tool, same prompt core, with vs. without access to the docs.

## Results

> Run `make eval` and copy the table from `results/<timestamp>/summary.md`.

| Mode | Tools | Execution accuracy (20 questions × 3 runs) |
|---|---|---|
| `with_docs` | `get_dbt_docs` + `run_sql` | _XX%_ |
| `no_docs` (schema-only baseline) | `run_sql` | _XX%_ |

Model: `_model id_` · Date: `_YYYY-MM-DD_`. The summary also breaks accuracy down
by question type (`simple`, `glossary`, `business_rule`, `metric`) and lists every
failure with the generated SQL for review.

## What's inside

```
data/generate_data.py      seeded generator for the raw marketing data (CSV seeds)
dbt_project/
  models/silver/           stg_* views: renaming, cents → BRL, channel grouping
  models/gold/             dim_campaigns, fct_ad_performance_daily, fct_conversions
  models/gold/_gold.yml    model + column descriptions, meta, tests
  models/gold/glossary.md  doc blocks: business_glossary, business_rules, metric_definitions
  tests/                   generic grain test + singular data tests
agent/
  docs_tool.py             tool 1: reads target/manifest.json + catalog.json
  sql_tool.py              tool 2: read-only DuckDB with guardrails
  llm.py                   Gemini adapter (google-genai, manual function calling)
  agent.py                 provider-agnostic agent loop, two modes
  prompts.py               system prompts (shared core + mode-specific part)
eval/
  golden_set.yaml          20 business questions with golden SQL and tags
  compare.py               execution-accuracy grader
  evaluate.py              runs the experiment, writes results/<ts>/summary.md
tests/test_offline.py      19 tests that need no API key, DuckDB or dbt
```

### Data

**FitLoop** is a fictional fitness-subscription app in Brazil, Mexico and Chile.
The data is synthetic and generated with a fixed seed, so every clone produces exactly
the same numbers and the golden answers stay stable. The schema follows what
ad-platform exports and product event streams look like:

| Raw seed | Rows | Content |
|---|---|---|
| `raw_campaigns` | 50 | campaign, channel, country, flight dates, budget, internal flag |
| `raw_ad_performance` | 2.7k | daily impressions, clicks, cost (cents) per campaign |
| `raw_conversion_events` | 17.6k | signup → trial_start → paid_subscription events, last-click attributed |

Some traps are planted on purpose. Column names don't explain them, but the docs do:

| Trap | Naive answer for "conversions in 2025" |
|---|---|
| "Conversion" = paid subscription, not any funnel event | 17,579 (all events) |
| QA campaigns (`is_internal`) create fake conversions | 2,743 (QA not excluded) |
| Organic conversions have `campaign_id = NULL` | 1,126 (inner join drops organic) |
| **Correct** | **1,593** |

Revenue is first-month subscription value only, which is why ROAS is below 1.

### The agent

* **Manual tool-calling loop** (ReAct style) on top of the Gemini API instead of the
  SDK's automatic function calling, so every step is traced (tool, arguments, output,
  tokens) and capped by `max_steps`.
* **`get_dbt_docs` uses progressive disclosure:** `index` returns a table of contents,
  and the agent then pulls only the models and pages it needs. Context stays small even
  in a large project. Accepted values come from dbt `accepted_values` tests and column
  types from `catalog.json`.
* **`run_sql` is read-only by construction:** DuckDB opened with `read_only=True`
  and external access disabled, a static check that rejects anything other than one
  SELECT, a timeout, and a row cap on what goes back to the model. SQL errors are
  returned as text so the model can correct itself.
* The LLM sits behind a two-method adapter, so the loop is tested with a scripted fake
  model and switching providers means writing one class.

### Evaluation

* **Metric: execution accuracy.** The agent's final SQL is executed and its result set
  is compared with the golden query's result. Column names, column order and extra
  columns are ignored. Numbers match within 0.1%. Row order counts only when the
  question asks for it.
* **Ablation:** `with_docs` vs `no_docs`. Both get the same core prompt and the same
  SQL tool and know that tables live in `gold`. The baseline can still inspect
  `information_schema`, so the gap measures *semantic* metadata, not schema access.
* **Repeated runs** (`--runs 3`) because agents are non-deterministic; the summary
  reports per-run accuracy and per-question pass counts (e.g. 2/3) to find flaky questions.
* **Tagged questions** show *where* the metadata helps (glossary terms vs business
  rules vs metric formulas vs the `simple` control group).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env   # add your GEMINI_API_KEY, then: export $(cat .env | xargs)

make dbt        # dbt build (seeds, models, tests) + dbt docs generate
make expected   # materialize golden answers to eval/expected_answers.json
make test       # offline tests
make ask Q="What was our total paid media spend in 2025?"
make eval       # the experiment → results/<timestamp>/summary.md
```

Optional: `cd dbt_project && dbt docs serve --profiles-dir .` to browse the same
documentation the agent reads.

## Limitations and next steps

* Synthetic data and a 20-question golden set: good for a controlled comparison, too
  small for strong statistical claims. Next: grow the set from real stakeholder questions.
* Execution accuracy can't grade the wording of the natural-language answer. Next:
  an LLM-as-judge check that the sentence matches the numbers.
* A third condition worth testing: the whole glossary stuffed into the system prompt
  vs fetched through the tool (accuracy vs tokens).
* Replace hand-written metric formulas with the dbt Semantic Layer (MetricFlow) so the
  agent queries governed metrics instead of writing the formulas itself.
* Run the eval in CI on every change to the dbt docs: prompts and docs are code and
  deserve regression tests.
