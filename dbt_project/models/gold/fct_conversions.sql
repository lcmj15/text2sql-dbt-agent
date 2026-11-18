-- Gold: one row per funnel event, last-click attributed to a campaign (or organic).
select
    conversion_id,
    user_id,
    campaign_id,
    conversion_type,
    converted_at,
    cast(converted_at as date)                         as conversion_date,
    cast(date_trunc('month', converted_at) as date)    as conversion_month,
    revenue_brl
from {{ ref('stg_conversion_events') }}
