-- Gold: one row per campaign.
select
    campaign_id,
    campaign_name,
    channel,
    channel_group,
    country_code,
    objective,
    start_date,
    end_date,
    is_internal,
    budget_brl
from {{ ref('stg_campaigns') }}
