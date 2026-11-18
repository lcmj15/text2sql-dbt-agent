-- Singular test: media cost can never be negative.
select *
from {{ ref('fct_ad_performance_daily') }}
where spend_brl < 0
