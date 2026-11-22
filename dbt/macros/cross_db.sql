{#
  The few places where DuckDB, Databricks (Spark SQL) and Snowflake disagree. Every model uses these instead of
  engine-specific functions, so the same SQL builds on all three targets. Semantics follow the original DuckDB build
  (warehouse.py), which the parity check compares against.
#}

{# text '2018-01-02T12:53:00.000Z' -> timestamp to the second (D6); NULL when not a valid date (e.g. Feb 29, 2017) #}
{% macro ts_from_text(expr) %}{{ return(adapter.dispatch('ts_from_text', 'p2p')(expr)) }}{% endmacro %}
{% macro default__ts_from_text(expr) %}try_cast(replace(left({{ expr }}, 19), 'T', ' ') as timestamp){% endmacro %}

{# whole seconds from a to b #}
{% macro diff_seconds(a, b) %}{{ return(adapter.dispatch('diff_seconds', 'p2p')(a, b)) }}{% endmacro %}
{% macro default__diff_seconds(a, b) %}datediff(second, {{ a }}, {{ b }}){% endmacro %}
{% macro duckdb__diff_seconds(a, b) %}date_diff('second', {{ a }}, {{ b }}){% endmacro %}
{% macro databricks__diff_seconds(a, b) %}(unix_timestamp({{ b }}) - unix_timestamp({{ a }})){% endmacro %}

{# hour boundaries crossed from a to b (DuckDB/Snowflake date_diff semantics: 10:59 -> 11:01 = 1) #}
{% macro diff_hours(a, b) %}{{ return(adapter.dispatch('diff_hours', 'p2p')(a, b)) }}{% endmacro %}
{% macro default__diff_hours(a, b) %}datediff(hour, {{ a }}, {{ b }}){% endmacro %}
{% macro duckdb__diff_hours(a, b) %}date_diff('hour', {{ a }}, {{ b }}){% endmacro %}
{% macro databricks__diff_hours(a, b) %}(floor(unix_timestamp({{ b }}) / 3600) - floor(unix_timestamp({{ a }}) / 3600)){% endmacro %}

{# timestamp (or date) plus n days / months, keeping the time of day #}
{% macro add_days(expr, n) %}{{ return(adapter.dispatch('add_days', 'p2p')(expr, n)) }}{% endmacro %}
{% macro default__add_days(expr, n) %}dateadd(day, {{ n }}, {{ expr }}){% endmacro %}
{% macro duckdb__add_days(expr, n) %}({{ expr }} + INTERVAL ({{ n }}) DAY){% endmacro %}
{% macro databricks__add_days(expr, n) %}timestampadd(DAY, {{ n }}, {{ expr }}){% endmacro %}

{% macro add_months(expr, n) %}{{ return(adapter.dispatch('add_months', 'p2p')(expr, n)) }}{% endmacro %}
{% macro default__add_months(expr, n) %}dateadd(month, {{ n }}, {{ expr }}){% endmacro %}
{% macro duckdb__add_months(expr, n) %}({{ expr }} + INTERVAL ({{ n }}) MONTH){% endmacro %}
{% macro databricks__add_months(expr, n) %}timestampadd(MONTH, {{ n }}, {{ expr }}){% endmacro %}

{# day of week with Sunday = 0 (DuckDB's dayofweek) #}
{% macro dow(expr) %}{{ return(adapter.dispatch('dow', 'p2p')(expr)) }}{% endmacro %}
{% macro default__dow(expr) %}mod(dayofweekiso({{ expr }}), 7){% endmacro %}
{% macro duckdb__dow(expr) %}dayofweek({{ expr }}){% endmacro %}
{% macro databricks__dow(expr) %}(dayofweek({{ expr }}) - 1){% endmacro %}

{# true/false -> 1/0 #}
{% macro as_int(cond) %}(case when {{ cond }} then 1 else 0 end){% endmacro %}

{# a timestamp literal #}
{% macro ts_lit(s) %}cast('{{ s }}' as timestamp){% endmacro %}

{# round a double to d decimals the way DuckDB does (round(x * 10^d) / 10^d on the binary value): Spark's round(x, d)
   goes through the shortest decimal text, so 77.975 (really 77.97499999...) becomes 77.98 there and 77.97 here #}
{% macro round_float(expr, d) %}{{ return(adapter.dispatch('round_float', 'p2p')(expr, d)) }}{% endmacro %}
{% macro default__round_float(expr, d) %}(round(({{ expr }}) * {{ 10 ** d }}) / {{ 10 ** d }}){% endmacro %}
{% macro duckdb__round_float(expr, d) %}round({{ expr }}, {{ d }}){% endmacro %}

{# a raw column whose name is a reserved word (timestamp, user): Snowflake keeps unquoted names in upper case #}
{% macro raw_col(name) %}{{ return(adapter.dispatch('raw_col', 'p2p')(name)) }}{% endmacro %}
{% macro default__raw_col(name) %}{{ adapter.quote(name) }}{% endmacro %}
{% macro snowflake__raw_col(name) %}"{{ name | upper }}"{% endmacro %}
