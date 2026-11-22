-- One row per gap between consecutive trusted steps, with the keys of its peer groups (same vendor; same item
-- category and value band), so a wait can be compared with the same gap elsewhere.
with steps as (
    select case_id, seq, activity, ts,
           lag(activity) over (partition by case_id order by seq) as from_activity,
           lag(seq)      over (partition by case_id order by seq) as from_seq,
           lag(ts)       over (partition by case_id order by seq) as from_ts
    from {{ ref('events') }}
    where is_canonical and seq is not null and ts_status in ('ok', 'repaired')
),
bands as (
    select case_id, vendor, item_category, ntile(5) over (order by value_eur, case_id) as value_band
    from {{ ref('cases') }}
)
select s.case_id, s.from_seq, s.seq as to_seq, s.from_activity, s.activity as to_activity,
       round(cast({{ diff_seconds('s.from_ts', 's.ts') }} as double) / 86400, 1) as days,
       b.vendor, b.item_category, b.value_band
from steps s join bands b on b.case_id = s.case_id
where s.from_activity is not null
