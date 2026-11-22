-- The event log. D7: identical rows are kept and counted; one canonical copy per group, with a trustworthy date,
-- is used for sequences, cycles and features. An out-of-range date with no candidate stays 'unresolved'.
with parsed as (
    select *,
           ts_original >= {{ ts_lit(var('valid_from')) }} and ts_original < {{ ts_lit(var('valid_to')) }} as in_range
    from {{ ref('stg_sap_events') }}
),
dated as (
    select p.*,
           coalesce(r.ts_status, case when p.in_range then 'ok' else 'unresolved' end)  as ts_status,
           case when r.event_id is null then p.ts_original else r.ts_repaired end      as ts
    from parsed p left join {{ ref('int_ts_repair') }} r on r.event_id = p.event_id
),
copies as (
    select *,
           count(*) over (partition by case_id, activity, ts_original, resource, user_id, value_eur)  as n_identical,
           row_number() over (partition by case_id, activity, ts_original, resource, user_id, value_eur
                              order by event_id)                                                     as copy_no
    from dated
),
flagged as (
    select *, ts_status in ('ok', 'repaired') and copy_no = 1 as is_canonical from copies
)
select event_id, case_id,
       case when is_canonical then row_number() over (partition by case_id, is_canonical order by ts, event_id) end
           as seq,
       activity, ts, ts_original, ts_status, resource, user_id, value_eur, n_identical, is_canonical
from flagged
