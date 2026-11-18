-- Gold: daily media delivery and cost per campaign. Grain: campaign_id x date_day.
select
    date_day,
    cast(date_trunc('month', date_day) as date) as date_month,
    campaign_id,
    impressions,
    clicks,
    spend_brl
from {{ ref('stg_ad_performance') }}
