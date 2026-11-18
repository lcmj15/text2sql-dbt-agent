-- Silver: rename raw ad-platform fields to business names and derive channel_group.
select
    id                                  as campaign_id,
    name                                as campaign_name,
    channel_code                        as channel,
    case
        when channel_code in ('paid_search', 'paid_social', 'display') then 'paid_media'
        when channel_code in ('email', 'push') then 'owned_media'
        when channel_code = 'affiliate' then 'partnerships'
        else 'other'
    end                                 as channel_group,
    country                             as country_code,
    objective,
    start_date,
    end_date,
    internal_flag                       as is_internal,
    lifetime_budget                     as budget_brl
from {{ ref('raw_campaigns') }}
