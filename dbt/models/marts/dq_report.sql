-- Every cleaning rule is counted; nothing is silently dropped.
{% set e = ref('events') %}{% set c = ref('cases') %}{% set y = ref('cycles') %}
select 'events_total' as check_name, count(*) as n, 'rows in the source CSV' as note from {{ e }}
union all select 'cases_total', count(*), 'PO line items (D2)' from {{ c }}
union all select 'dates_repaired', sum({{ as_int("ts_status = 'repaired'") }}),
                 'year typo fixed: one plausible year, or a same-minute companion (D1)' from {{ e }}
union all select 'dates_duplicate', sum({{ as_int("ts_status = 'duplicate'") }}),
                 'bad-date copy of an existing event (D1)' from {{ e }}
union all select 'dates_unresolved', sum({{ as_int("ts_status = 'unresolved'") }}),
                 'kept, excluded from sequences and durations (D1)' from {{ e }}
union all select 'cases_with_bad_dates', sum({{ as_int('n_bad_dates > 0') }}),
                 'lines with at least one out-of-range date' from {{ c }}
union all select 'rows_identical_extra',
                 sum({{ as_int("n_identical > 1 and not is_canonical and ts_status in ('ok', 'repaired')") }}),
                 'identical copies kept but not canonical (D7)' from {{ e }}
union all select 'events_canonical', sum({{ as_int('is_canonical') }}), 'rows used for sequences and cycles' from {{ e }}
union all select 'cycles_total', count(*), 'payment cycles across all lines (D4)' from {{ y }}
union all select 'cycles_open', sum({{ as_int('not is_closed') }}), 'cycles with no closing payment yet (D4)' from {{ y }}
union all select 'events_null_value', sum({{ as_int('value_eur is null') }}),
                 'cumulative net worth missing or unparsable' from {{ e }}
union all select 'cases_value_changes', count(*), 'value differs across events (D3 uses Create PO Item)'
          from (select case_id from {{ e }} group by case_id having count(distinct value_eur) > 1) v
