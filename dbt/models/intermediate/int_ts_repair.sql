-- D1: for each out-of-range date, try the same day and minute in 2017-2019. A candidate is a duplicate when the
-- line already has that event at that minute; it is repaired when exactly one year fits the line's own timeline
-- (+-60 days), or when one candidate is tied to another event at the same minute (e.g. invoice + debit memo).
with parsed as (
    select *,
           ts_original >= {{ ts_lit(var('valid_from')) }} and ts_original < {{ ts_lit(var('valid_to')) }} as in_range
    from {{ ref('stg_sap_events') }}
),
line_window as (
    select case_id, min(ts_original) as first_ts, max(ts_original) as last_ts
    from parsed where in_range group by case_id
),
in_keys as (select distinct case_id, activity, ts_original from parsed where in_range),
in_ts   as (select distinct case_id, ts_original from parsed where in_range),
candidates as (
    select b.event_id, b.case_id, b.activity,
           {{ ts_from_text("concat(cast(y.yr as " ~ dbt.type_string() ~ "), substr(b.ts_text, 5))") }} as candidate_ts
    from parsed b
    cross join (select 2017 as yr union all select 2018 union all select 2019) y
    where not b.in_range
),
scored as (
    select c.event_id, c.candidate_ts,
           {{ as_int('k.case_id is not null') }}                                       as has_twin,
           {{ as_int('t.case_id is not null') }}                                       as has_companion,
           {{ as_int("c.candidate_ts between " ~ add_days('w.first_ts', -var('repair_window_days'))
                     ~ " and " ~ add_days('w.last_ts', var('repair_window_days'))) }} as plausible
    from candidates c
    left join line_window w on w.case_id = c.case_id
    left join in_keys k on k.case_id = c.case_id and k.activity = c.activity and k.ts_original = c.candidate_ts
    left join in_ts t   on t.case_id = c.case_id and t.ts_original = c.candidate_ts
    where c.candidate_ts is not null
),
decided as (
    select event_id,
           max(has_twin) = 1                                                       as is_duplicate,
           sum(plausible)                                                          as n_plausible,
           sum(plausible * has_companion)                                          as n_with_companion,
           max(case when plausible = 1 then candidate_ts end)                      as only_plausible,
           max(case when plausible = 1 and has_companion = 1 then candidate_ts end) as only_companion
    from scored group by event_id
)
select event_id,
       case when is_duplicate          then 'duplicate'
            when n_plausible = 1       then 'repaired'
            when n_with_companion = 1  then 'repaired'
            else 'unresolved' end                                    as ts_status,
       case when is_duplicate          then null
            when n_plausible = 1       then only_plausible
            when n_with_companion = 1  then only_companion end       as ts_repaired
from decided
