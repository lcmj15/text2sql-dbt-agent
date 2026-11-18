-- Silver: funnel events (signup -> trial_start -> paid_subscription), revenue in BRL.
select
    event_id                            as conversion_id,
    user_id,
    campaign_id,                        -- null = organic (no paid/owned touchpoint)
    event_type                          as conversion_type,
    event_ts                            as converted_at,
    cast(revenue_cents as double) / 100 as revenue_brl
from {{ ref('raw_conversion_events') }}
