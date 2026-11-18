{% test unique_combination(model, columns) %}
-- Fails if the combination of columns is not unique (grain test, no package needed).
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
