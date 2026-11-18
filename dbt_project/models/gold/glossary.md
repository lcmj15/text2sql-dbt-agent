{% docs business_glossary %}
# FitLoop Marketing – Business Glossary

| Term | Definition | How to compute in SQL (gold schema) |
|---|---|---|
| **Conversion** | A **paid subscription**. When the business says "conversions" without a qualifier it always means paid subscriptions, never signups or trials. | `fct_conversions` where `conversion_type = 'paid_subscription'` |
| **Lead** / **Signup** | A user who created an account. | `conversion_type = 'signup'` |
| **Trial** / **Trial start** | A user who started the 7-day free trial. | `conversion_type = 'trial_start'` |
| **Organic** | A funnel event with no attributed campaign. | `fct_conversions.campaign_id is null` |
| **Paid media** | Channels where we buy media: `paid_search`, `paid_social`, `display`. | `dim_campaigns.channel_group = 'paid_media'` |
| **Owned media** | Channels we own: `email`, `push`. They have zero media cost. | `channel_group = 'owned_media'` |
| **Partnerships** | Affiliate channel, paid on a CPA basis. | `channel_group = 'partnerships'` |
| **Internal / QA campaign** | Tracking-test campaigns created by the growth team. Their clicks and conversions are fake. | `dim_campaigns.is_internal = true` |
| **Active campaign (on a date)** | A non-internal campaign whose flight includes that date. | `start_date <= d and end_date >= d and not is_internal` |
| **Revenue** | First-month subscription value of paid conversions, in BRL. | `sum(revenue_brl)` over paid subscriptions |
| **Quarter / Half** | Calendar quarters (Q1 = Jan–Mar …). H1 = Jan–Jun, H2 = Jul–Dec. | filter on the date column |
{% enddocs %}


{% docs business_rules %}
# Business rules (apply to every metric unless the question says otherwise)

1. **Always exclude internal/QA campaigns** (`dim_campaigns.is_internal = true`) from spend, clicks, impressions, conversions and revenue. To exclude them from `fct_conversions` without losing organic rows use:
   `left join gold.dim_campaigns c using (campaign_id) ... where coalesce(c.is_internal, false) = false`
2. **Company-level totals include organic conversions.** An `inner join` to `dim_campaigns` silently drops organic rows (campaign_id is null). Only drop organic rows when the question is cut by channel, country or campaign.
3. **Country of a conversion = country of its attributed campaign.** Organic conversions have no country.
4. **Dates:** conversions are dated by `conversion_date` (when the event happened, not when the click happened). Media metrics are dated by `date_day`.
5. **Money** is always in BRL (columns ending in `_brl`). Raw tables store cents; never use raw tables.
6. **Rates and ratios** (CTR, CVR, trial-to-paid) are returned as fractions between 0 and 1, computed as ratio of sums (never the average of daily ratios).
7. Use only the `gold` schema for analysis. `raw` and `silver` are internal layers.
{% enddocs %}


{% docs metric_definitions %}
# Metric definitions

| Metric | Formula | Notes |
|---|---|---|
| **Spend** | `sum(fct_ad_performance_daily.spend_brl)` | BRL, excludes internal campaigns |
| **CTR** | `sum(clicks) / sum(impressions)` | fraction |
| **CPC** | `sum(spend_brl) / sum(clicks)` | BRL per click |
| **CAC** (customer acquisition cost) | `spend / number of conversions (paid subscriptions)` attributed to the same campaigns and period | Only meaningful for paid media and partnerships. Divide by paid subscriptions, **not** signups. |
| **ROAS** | `revenue_brl of paid subscriptions / spend_brl` | same campaigns and period |
| **CVR** (conversion rate) | `conversions (paid subscriptions) / clicks` | fraction |
| **Trial-to-paid rate** | `count(paid_subscription) / count(trial_start)` | fraction, same period |
| **Budget utilization** | `lifetime spend / budget_brl` | owned media has budget 0 |
{% enddocs %}
