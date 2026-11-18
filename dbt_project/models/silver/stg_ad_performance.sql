-- Silver: one row per campaign per day; cost converted from cents to BRL.
select
    report_date                         as date_day,
    campaign_id,
    impressions,
    clicks,
    cast(cost_cents as double) / 100    as spend_brl
from {{ ref('raw_ad_performance') }}
