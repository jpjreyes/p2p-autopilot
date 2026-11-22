-- One row per PO line item (D2); value = the ordered amount at "Create Purchase Order Item" (D3).
with attrs as (
    select case_id,
           any_value(case_purchasing_document)            as po,
           any_value(case_item)                           as item,
           any_value(case_item_category)                  as item_category,
           any_value(case_item_type)                      as item_type,
           any_value(case_vendor)                         as vendor,
           any_value(case_company)                        as company,
           any_value(case_spend_area_text)                as spend_area,
           any_value(case_sub_spend_area_text)            as sub_spend_area,
           any_value(case_document_type)                  as document_type,
           any_value(case_gr_based_inv_verif) = 'true'    as gr_based_inv_verif,
           any_value(case_goods_receipt) = 'true'         as goods_receipt_flag
    from {{ ref('stg_sap_events') }} group by case_id
),
ordered as (
    select case_id, value_eur,
           row_number() over (partition by case_id order by event_id) as rn
    from {{ ref('events') }}
    where activity = 'Create Purchase Order Item' and value_eur is not null
),
stats as (
    select case_id,
           count(*)                                                                  as n_events,
           sum({{ as_int("ts_status <> 'ok'") }})                                    as n_bad_dates,
           min(case when ts_status in ('ok', 'repaired') then ts end)                as start_ts,
           max(case when ts_status in ('ok', 'repaired') then ts end)                as end_ts
    from {{ ref('events') }} group by case_id
)
select a.*, o.value_eur, s.n_events, s.n_bad_dates, s.start_ts, s.end_ts,
       {{ round_float("cast(" ~ diff_seconds('s.start_ts', 's.end_ts') ~ " as double) / 86400", 2) }} as throughput_days
from attrs a
join stats s on s.case_id = a.case_id
left join ordered o on o.case_id = a.case_id and o.rn = 1
