-- Singular test: only paid subscriptions carry revenue.
select *
from {{ ref('fct_conversions') }}
where conversion_type <> 'paid_subscription' and revenue_brl <> 0
