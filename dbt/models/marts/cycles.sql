-- D4: each payment (Clear Invoice) closes the cycle it belongs to. Canonical events only (D7).
with numbered as (
    select case_id, event_id, seq, activity, ts,
           1 + coalesce(sum({{ as_int("activity = 'Clear Invoice'") }}) over (
                   partition by case_id order by seq rows between unbounded preceding and 1 preceding), 0) as cycle_no
    from {{ ref('events') }}
    where is_canonical
)
select case_id,
       cycle_no,
       min(ts)                                                                       as start_ts,
       max(ts)                                                                       as end_ts,
       {{ round_float("cast(" ~ diff_seconds('min(ts)', 'max(ts)') ~ " as double) / 86400", 2) }}    as days,
       count(*)                                                                      as n_events,
       max({{ as_int("activity = 'Clear Invoice'") }}) = 1                           as is_closed,
       max(case when activity = 'Clear Invoice' then event_id end)                   as closing_event_id
from numbered
group by case_id, cycle_no
