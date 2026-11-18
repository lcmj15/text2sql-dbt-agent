"""
Build an in-memory SQLite copy of the gold layer from the seed CSVs.

Only used by the offline tests so they run in CI without DuckDB, dbt or an API
key. The transformations mirror the dbt models one to one.
"""
import csv
import sqlite3
from pathlib import Path

SEEDS = Path(__file__).resolve().parents[1] / "dbt_project" / "seeds"

CHANNEL_GROUP = {"paid_search": "paid_media", "paid_social": "paid_media", "display": "paid_media",
                 "email": "owned_media", "push": "owned_media", "affiliate": "partnerships"}


def _read(name):
    with (SEEDS / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("attach ':memory:' as gold")
    conn.execute("""create table gold.dim_campaigns (campaign_id integer, campaign_name text,
        channel text, channel_group text, country_code text, objective text, start_date text,
        end_date text, is_internal boolean, budget_brl double)""")
    conn.executemany("insert into gold.dim_campaigns values (?,?,?,?,?,?,?,?,?,?)", [
        (int(r["id"]), r["name"], r["channel_code"], CHANNEL_GROUP[r["channel_code"]], r["country"],
         r["objective"], r["start_date"], r["end_date"], r["internal_flag"] == "true",
         float(r["lifetime_budget"])) for r in _read("raw_campaigns")])
    conn.execute("""create table gold.fct_ad_performance_daily (date_day text, date_month text,
        campaign_id integer, impressions integer, clicks integer, spend_brl double)""")
    conn.executemany("insert into gold.fct_ad_performance_daily values (?,?,?,?,?,?)", [
        (r["report_date"], r["report_date"][:8] + "01", int(r["campaign_id"]), int(r["impressions"]),
         int(r["clicks"]), int(r["cost_cents"]) / 100) for r in _read("raw_ad_performance")])
    conn.execute("""create table gold.fct_conversions (conversion_id text, user_id text,
        campaign_id integer, conversion_type text, converted_at text, conversion_date text,
        conversion_month text, revenue_brl double)""")
    conn.executemany("insert into gold.fct_conversions values (?,?,?,?,?,?,?,?)", [
        (r["event_id"], r["user_id"], int(r["campaign_id"]) if r["campaign_id"] else None,
         r["event_type"], r["event_ts"], r["event_ts"][:10], r["event_ts"][:8] + "01",
         int(r["revenue_cents"]) / 100) for r in _read("raw_conversion_events")])
    return conn