"""
Generate a reproducible synthetic marketing dataset for "FitLoop", a fictional
fitness-subscription app operating in Brazil, Mexico and Chile.

The schema mimics what you get from ad-platform exports (Google Ads / Meta)
plus a product-analytics event stream. A fixed seed means anyone who clones
the repo gets exactly the same numbers, so the golden-set answers are stable.

Some "traps" are planted on purpose. They are things a model cannot guess
from column names alone and that only the dbt docs / glossary explain:
  * QA campaigns (is_internal = true) generate fake conversions that must be
    excluded from every business metric.
  * "Conversion" in the business means a *paid subscription*, not a signup.
  * Organic conversions have campaign_id = NULL and must still be counted in
    company totals (an INNER JOIN to campaigns silently drops them).
  * Raw money columns are in cents; gold columns are in BRL.

Output: CSV files in dbt_project/seeds/
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
OUT_DIR = Path(__file__).resolve().parents[1] / "dbt_project" / "seeds"

COUNTRIES = ["BR", "MX", "CL"]
COUNTRY_WEIGHT = {"BR": 1.0, "MX": 0.6, "CL": 0.3}

# channel -> (daily impressions base, CTR, CPC in cents, signup rate per click)
CHANNELS = {
    "paid_search": (9_000, 0.045, 210, 0.060),
    "paid_social": (40_000, 0.012, 95, 0.035),
    "display": (60_000, 0.004, 60, 0.015),
    "affiliate": (5_000, 0.030, 180, 0.050),
    "email": (12_000, 0.025, 0, 0.040),  # owned media: no media cost
    "push": (15_000, 0.015, 0, 0.030),  # owned media: no media cost
}
TRIAL_RATE = {"paid_search": 0.55, "paid_social": 0.45, "display": 0.35,
              "affiliate": 0.50, "email": 0.60, "push": 0.50}
PAID_RATE = {"paid_search": 0.42, "paid_social": 0.33, "display": 0.25,
             "affiliate": 0.38, "email": 0.50, "push": 0.40}
PLAN_PRICES_CENTS = [8990, 12990, 19990]  # monthly plans, already in BRL
OBJECTIVES = ["acquisition", "reactivation", "brand"]


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def build_campaigns(rng: random.Random) -> list[dict]:
    campaigns = []
    cid = 1000
    quarters = [(date(2025, 1, 1), date(2025, 3, 31)), (date(2025, 4, 1), date(2025, 6, 30)),
                (date(2025, 7, 1), date(2025, 9, 30)), (date(2025, 10, 1), date(2025, 12, 31))]
    for qi, (qs, qe) in enumerate(quarters, start=1):
        for channel in CHANNELS:
            # every channel runs in BR each quarter; MX/CL alternate
            countries = ["BR"] + (["MX"] if qi % 2 == 1 else ["CL"])
            if channel in ("paid_search", "paid_social") and qi >= 3:
                countries = ["BR", "MX", "CL"]
            for country in countries:
                if channel in ("email", "push") and country != "BR" and rng.random() < 0.5:
                    continue
                cid += 1
                start = qs + timedelta(days=rng.randint(0, 20))
                end = min(qe, start + timedelta(days=rng.randint(35, 75)))
                objective = "reactivation" if channel in ("email", "push") else rng.choice(
                    ["acquisition", "acquisition", "brand"])
                budget = 0 if CHANNELS[channel][2] == 0 else int(
                    rng.uniform(0.75, 1.15) * CHANNELS[channel][0] * CHANNELS[channel][1]
                    * CHANNELS[channel][2] / 100 * COUNTRY_WEIGHT[country] * (end - start).days)
                campaigns.append({
                    "id": cid,
                    "name": f"{country}_{channel}_{objective}_Q{qi}_2025",
                    "channel_code": channel,
                    "country": country,
                    "objective": objective,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "internal_flag": "false",
                    "lifetime_budget": budget,
                })
    # QA / tracking-test campaigns created by the growth team
    for i, (s, e) in enumerate([(date(2025, 2, 3), date(2025, 2, 28)),
                                (date(2025, 6, 2), date(2025, 7, 15)),
                                (date(2025, 9, 1), date(2025, 11, 30))], start=1):
        cid += 1
        campaigns.append({
            "id": cid, "name": f"BR_paid_social_tracking_check_{i}",
            "channel_code": "paid_social", "country": "BR", "objective": "acquisition",
            "start_date": s.isoformat(), "end_date": e.isoformat(),
            "internal_flag": "true", "lifetime_budget": 2000,
        })
    return campaigns


def main() -> None:
    rng = random.Random(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    campaigns = build_campaigns(rng)

    perf_rows, conv_rows = [], []
    conv_id, user_id = 0, 500_000

    def add_event(uid, campaign_id, etype, ts, revenue_cents=0):
        nonlocal conv_id
        conv_id += 1
        conv_rows.append({
            "event_id": f"ev_{conv_id:07d}", "user_id": f"u_{uid}",
            "campaign_id": "" if campaign_id is None else campaign_id,
            "event_type": etype, "event_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "revenue_cents": revenue_cents,
        })

    for c in campaigns:
        imp_base, ctr, cpc, signup_rate = CHANNELS[c["channel_code"]]
        internal = c["internal_flag"] == "true"
        w = COUNTRY_WEIGHT[c["country"]]
        for d in daterange(date.fromisoformat(c["start_date"]), date.fromisoformat(c["end_date"])):
            weekend = 0.8 if d.weekday() >= 5 else 1.0
            if internal:
                impressions = rng.randint(50, 200)
                clicks = rng.randint(5, 20)
                spend_cents = rng.randint(2000, 6000)
            else:
                impressions = int(imp_base * w * weekend * rng.uniform(0.7, 1.3))
                clicks = int(impressions * ctr * rng.uniform(0.8, 1.2))
                spend_cents = int(clicks * cpc * rng.uniform(0.85, 1.15))
            perf_rows.append({"report_date": d.isoformat(), "campaign_id": c["id"],
                              "impressions": impressions, "clicks": clicks,
                              "cost_cents": spend_cents})

            # funnel events attributed (last click) to this campaign
            if internal:
                # QA bots: many fake signups and test purchases at full price
                n_signups = rng.randint(6, 14)
                trial_p, paid_p = 0.9, 0.8
            else:
                n_signups = sum(1 for _ in range(clicks) if rng.random() < signup_rate * 0.25)
                trial_p, paid_p = TRIAL_RATE[c["channel_code"]], PAID_RATE[c["channel_code"]]
            for _ in range(n_signups):
                user_id += 1
                ts = datetime(d.year, d.month, d.day) + timedelta(seconds=rng.randint(0, 86_399))
                add_event(user_id, c["id"], "signup", ts)
                if rng.random() < trial_p:
                    t_ts = ts + timedelta(hours=rng.randint(0, 48))
                    add_event(user_id, c["id"], "trial_start", t_ts)
                    if rng.random() < paid_p:
                        # paid after the 7-day trial -> can land in the next month
                        p_ts = t_ts + timedelta(days=7, minutes=rng.randint(0, 600))
                        if p_ts.year == 2025:
                            add_event(user_id, c["id"], "paid_subscription", p_ts,
                                      rng.choice(PLAN_PRICES_CENTS))

    # organic funnel (no campaign) every day of 2025
    for d in daterange(date(2025, 1, 1), date(2025, 12, 31)):
        for _ in range(rng.randint(3, 9)):
            user_id += 1
            ts = datetime(d.year, d.month, d.day) + timedelta(seconds=rng.randint(0, 86_399))
            add_event(user_id, None, "signup", ts)
            if rng.random() < 0.5:
                t_ts = ts + timedelta(hours=rng.randint(0, 48))
                add_event(user_id, None, "trial_start", t_ts)
                if rng.random() < 0.45:
                    p_ts = t_ts + timedelta(days=7, minutes=rng.randint(0, 600))
                    if p_ts.year == 2025:
                        add_event(user_id, None, "paid_subscription", p_ts,
                                  rng.choice(PLAN_PRICES_CENTS))

    conv_rows.sort(key=lambda r: r["event_ts"])

    def write(name, rows):
        path = OUT_DIR / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {path.relative_to(OUT_DIR.parents[1])}: {len(rows):,} rows")

    write("raw_campaigns", campaigns)
    write("raw_ad_performance", perf_rows)
    write("raw_conversion_events", conv_rows)


if __name__ == "__main__":
    main()