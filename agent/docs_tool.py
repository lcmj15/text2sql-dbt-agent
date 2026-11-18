"""
Tool 1 – get_dbt_docs: gives the agent the *semantic layer* of the warehouse.

Primary source is dbt's own artifacts:
  * target/manifest.json  – model/column descriptions, meta, doc blocks, tests
  * target/catalog.json   – column data types (written by `dbt docs generate`)
These are the same files that power the `dbt docs` website, so the agent and
the humans read exactly the same documentation.

If the artifacts do not exist yet, it falls back to parsing the YAML and
markdown files in the project (handy for tests and first-time setup).

The tool uses *progressive disclosure*: "index" returns a short table of
contents and the agent asks only for the models / docs it needs. This keeps
the context small, which matters once a project has hundreds of models.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GOLD_SCHEMA = "gold"


@dataclass
class ColumnDoc:
    name: str
    description: str = ""
    data_type: str = ""
    accepted_values: list[str] = field(default_factory=list)


@dataclass
class ModelDoc:
    name: str
    description: str
    meta: dict
    columns: dict[str, ColumnDoc]


class DbtDocs:
    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self.models: dict[str, ModelDoc] = {}
        self.doc_blocks: dict[str, str] = {}
        manifest = self.project_dir / "target" / "manifest.json"
        if manifest.exists():
            self.source = "manifest.json"
            self._load_manifest(manifest)
        else:
            self.source = "yaml files (run `dbt docs generate` to use the manifest)"
            self._load_yaml()

    # ------------------------------------------------------------------ loaders
    def _load_manifest(self, path: Path) -> None:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        project = manifest["metadata"].get("project_name")
        for node in manifest["nodes"].values():
            if node["resource_type"] == "model" and node.get("schema") == GOLD_SCHEMA:
                self.models[node["name"]] = ModelDoc(
                    name=node["name"],
                    description=_clean(node.get("description", "")),
                    meta=node.get("meta") or node.get("config", {}).get("meta", {}) or {},
                    columns={
                        c["name"]: ColumnDoc(c["name"], _clean(c.get("description", "")),
                                             c.get("data_type") or "")
                        for c in node.get("columns", {}).values()
                    },
                )
        # accepted_values tests tell the agent the valid enum values of a column
        for node in manifest["nodes"].values():
            meta = node.get("test_metadata") or {}
            if node["resource_type"] == "test" and meta.get("name") == "accepted_values":
                model_name = (node.get("attached_node") or "").split(".")[-1]
                col = node.get("column_name") or meta.get("kwargs", {}).get("column_name")
                values = meta.get("kwargs", {}).get("values", [])
                self._set_accepted(model_name, col, values)
        for doc in manifest.get("docs", {}).values():
            if doc.get("package_name") == project:
                self.doc_blocks[doc["name"]] = doc["block_contents"].strip()
        catalog = path.parent / "catalog.json"
        if catalog.exists():
            for node in json.loads(catalog.read_text(encoding="utf-8")).get("nodes", {}).values():
                model = self.models.get(node["metadata"]["name"])
                if not model:
                    continue
                for col_name, col in node["columns"].items():
                    key = col_name.lower()
                    model.columns.setdefault(key, ColumnDoc(key))
                    model.columns[key].data_type = col["type"]

    def _load_yaml(self) -> None:
        gold_dir = self.project_dir / "models" / GOLD_SCHEMA
        for yml in gold_dir.glob("*.yml"):
            for m in (yaml.safe_load(yml.read_text(encoding="utf-8")) or {}).get("models", []):
                cols = {}
                for c in m.get("columns", []):
                    col = ColumnDoc(c["name"], _clean(c.get("description", "")))
                    for t in c.get("tests", []) or []:
                        if isinstance(t, dict) and "accepted_values" in t:
                            av = t["accepted_values"]
                            # dbt >= 1.10 nests test params under `arguments`
                            col.accepted_values = av.get("arguments", av)["values"]
                    cols[c["name"]] = col
                self.models[m["name"]] = ModelDoc(m["name"], _clean(m.get("description", "")),
                                                  m.get("meta", {}), cols)
        for md in gold_dir.glob("*.md"):
            for name, body in re.findall(r"{%\s*docs\s+(\w+)\s*%}(.*?){%\s*enddocs\s*%}",
                                         md.read_text(encoding="utf-8"), flags=re.S):
                self.doc_blocks[name] = body.strip()

    def _set_accepted(self, model_name: str, col: str | None, values: list) -> None:
        model = self.models.get(model_name)
        if model and col:
            model.columns.setdefault(col, ColumnDoc(col)).accepted_values = list(values)

    # -------------------------------------------------------------- rendering
    def index(self) -> str:
        lines = ["# Analytics documentation (dbt)", "",
                 f"Schema `{GOLD_SCHEMA}` contains the business-ready models:"]
        for m in self.models.values():
            lines.append(f"- `{GOLD_SCHEMA}.{m.name}`: {m.description}")
        lines += ["", "Business documentation pages:"]
        for name, body in self.doc_blocks.items():
            title = next((l.lstrip("# ") for l in body.splitlines() if l.strip()), name)
            lines.append(f"- `{name}`: {title}")
        lines += ["", "Call get_dbt_docs with a model name or a page name for details."]
        return "\n".join(lines)

    def model(self, name: str) -> str:
        m = self.models[name]
        lines = [f"# {GOLD_SCHEMA}.{m.name}", "", m.description]
        if m.meta:
            lines.append("Meta: " + ", ".join(f"{k}={v}" for k, v in m.meta.items()))
        lines += ["", "| column | type | description |", "|---|---|---|"]
        for c in m.columns.values():
            desc = c.description
            if c.accepted_values:
                desc += f" Accepted values: {', '.join(map(str, c.accepted_values))}."
            lines.append(f"| {c.name} | {c.data_type or '?'} | {desc} |")
        return "\n".join(lines)

    def get(self, topic: str) -> str:
        topic = (topic or "index").strip().removeprefix(f"{GOLD_SCHEMA}.")
        if topic in ("", "index"):
            return self.index()
        if topic in self.models:
            return self.model(topic)
        if topic in self.doc_blocks:
            return self.doc_blocks[topic]
        valid = ["index", *self.models, *self.doc_blocks]
        return f"ERROR: unknown topic '{topic}'. Valid topics: {', '.join(valid)}"


def _clean(text: str) -> str:
    return " ".join(text.split())


TOOL_SPEC = {
    "name": "get_dbt_docs",
    "description": (
        "Read the dbt documentation of the analytics warehouse: model and column "
        "descriptions, accepted values, the business glossary, business rules and metric "
        "definitions. Call with topic='index' first to see what exists, then with a model "
        "name (e.g. 'fct_conversions') or a page name (e.g. 'business_rules')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string",
                      "description": "'index', a model name, or a documentation page name."}
        },
        "required": ["topic"],
    },
}