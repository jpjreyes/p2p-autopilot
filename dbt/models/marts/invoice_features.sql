-- The payment-block model's features at invoice receipt (D18, D18b), one row per PO line with an invoice.
-- Leak-free by construction: only events strictly before the invoice (plus the invoice itself); vendor history only
-- from months whose 60-day outcome was already known (3+ months earlier). Port of predict.build_frame('invoice').
{% set prior = {
    "Change Price": "n_change_price", "Change Quantity": "n_change_qty", "Record Goods Receipt": "n_gr",
    "Receive Order Confirmation": "n_order_conf", "Cancel Goods Receipt": "n_cancel_gr",
    "Create Purchase Requisition Item": "has_requisition", "Vendor creates invoice": "n_vendor_invoice",
    "Change Approval for Purchase Order": "n_change_approval", "Record Service Entry Sheet": "n_service_entry"} %}
{% set categorical = ["item_category", "item_type", "document_type", "spend_area", "sub_spend_area", "company"] %}
with trusted as (
    select * from {{ ref('events') }} where is_canonical and ts_status in ('ok', 'repaired')
),
f as (
    select case_id,
           min(case when activity = 'Create Purchase Order Item' then ts end) as po_ts,
           min(case when activity = 'Record Invoice Receipt' then ts end)     as ir_ts
    from trusted group by case_id
),
ir_user as (  -- who recorded the first invoice (first non-empty user)
    select case_id, user_id,
           row_number() over (partition by case_id order by ts, event_id) as rn
    from trusted where activity = 'Record Invoice Receipt' and user_id is not null
),
labelled as (  -- outcome: a payment block removed within the horizon after the invoice
    select f.case_id
    from f join {{ ref('events') }} e
      on e.case_id = f.case_id and e.is_canonical and e.activity = 'Remove Payment Block'
     and e.ts > f.ir_ts and e.ts <= {{ add_days('f.ir_ts', var('horizon_days')) }}
    group by f.case_id
),
lines as (
    select c.*, f.po_ts, f.ir_ts, u.user_id as ir_user,
           {{ as_int('lb.case_id is not null') }}  as label,
           date_trunc('month', f.ir_ts)            as ir_month,
           date_trunc('month', f.ir_ts)            as cut_month
    from {{ ref('cases') }} c
    join f on f.case_id = c.case_id
    left join ir_user u on u.case_id = c.case_id and u.rn = 1
    left join labelled lb on lb.case_id = c.case_id
    where f.ir_ts is not null and f.po_ts is not null
),
vendor_month as (select vendor, ir_month, count(*) as n, sum(label) as blocked from lines group by vendor, ir_month),
grid as (select distinct vendor, cut_month as at_month from lines),
vendor_hist as (  -- lagged 3 months: every outcome counted was already known
    select g.vendor, g.at_month,
           coalesce(sum(m.n), 0) as vendor_lines, coalesce(sum(m.blocked), 0) as vendor_blocked
    from grid g left join vendor_month m
      on m.vendor = g.vendor and m.ir_month <= {{ add_months('g.at_month', -3) }}
    group by g.vendor, g.at_month
),
global_rate as (
    select avg(cast(label as double)) as rate from lines where ir_ts < {{ ts_lit(var('train_end')) }}
),
seen as (  -- events known at the decision point: strictly before the invoice, plus the invoice itself
    select l.case_id, e.activity, e.ts, e.event_id, e.value_eur
    from lines l join {{ ref('events') }} e
      on e.case_id = l.case_id and e.is_canonical and e.ts <= l.ir_ts
     and (e.ts < l.ir_ts or e.activity = 'Record Invoice Receipt')
),
ev as (
    select l.case_id,
           {% for a, c in prior.items() %}sum({{ as_int("s.activity = '" ~ a ~ "'") }}) as {{ c }},
           {% endfor %}sum({{ as_int("s.activity = 'Record Goods Receipt'") }}) = 0       as no_gr_yet,
           max(case when s.activity = 'Record Goods Receipt' then s.ts end)               as last_gr
    from lines l left join seen s on s.case_id = l.case_id
    group by l.case_id
),
value_now as (  -- the line's latest known value
    select case_id, value_eur,
           row_number() over (partition by case_id order by ts desc, event_id) as rn
    from seen where value_eur is not null
),
vday as (  -- the vendor's recent activity per day: blocks removed and invoices recorded
    select c.vendor, cast(e.ts as date) as day,
           sum({{ as_int("e.activity = 'Remove Payment Block'") }})   as rpb,
           sum({{ as_int("e.activity = 'Record Invoice Receipt'") }}) as ir
    from {{ ref('events') }} e join {{ ref('cases') }} c on c.case_id = e.case_id
    where e.is_canonical and e.activity in ('Remove Payment Block', 'Record Invoice Receipt')
    group by c.vendor, cast(e.ts as date)
),
recent as (
    select l.case_id, sum(v.rpb) as vendor_rpb_30d, sum(v.ir) as vendor_ir_30d
    from lines l join vday v
      on v.vendor = l.vendor
     and v.day >= {{ add_days('cast(l.ir_ts as date)', -30) }} and v.day < cast(l.ir_ts as date)
    group by l.case_id
),
po as (select po, count(*) as po_lines from {{ ref('cases') }} group by po),
po_prev as (  -- other lines of the same PO whose block was removed before the invoice
    select l.case_id, count(distinct e.case_id) as po_blocked_before
    from lines l
    join {{ ref('cases') }} c2 on c2.po = l.po and c2.case_id <> l.case_id
    join {{ ref('events') }} e on e.case_id = c2.case_id and e.activity = 'Remove Payment Block' and e.ts < l.ir_ts
    group by l.case_id
)
select l.case_id, l.ir_ts, l.label, l.value_eur, l.vendor,
       {% for c in categorical %}coalesce(l.{{ c }}, 'NA') as {{ c }}, {% endfor %}
       coalesce(l.ir_user, 'NA')                                                   as ir_user,
       {{ as_int('l.gr_based_inv_verif') }}                                        as gr_based_inv_verif,
       ln(1 + greatest(l.value_eur, 0))                                            as log_value,
       cast({{ diff_hours('l.po_ts', 'l.ir_ts') }} as double) / 24                 as days_po_to_cut,
       {{ as_int('ev.no_gr_yet') }}                                                as invoice_before_gr,
       {% for c in prior.values() %}ev.{{ c }}, {% endfor %}
       po.po_lines,
       coalesce(pp.po_blocked_before, 0)                                           as po_blocked_before,
       vn.value_eur / nullif(l.value_eur, 0)                                       as value_ratio,
       count(*) over (partition by l.vendor, l.ir_ts)                              as inv_lines,
       max({{ as_int('ev.no_gr_yet') }}) over (partition by l.vendor, l.ir_ts)     as inv_any_no_gr,
       avg(cast({{ as_int('ev.no_gr_yet') }} as double)) over (partition by l.vendor, l.ir_ts) as inv_share_no_gr,
       ln(1 + sum(greatest(l.value_eur, 0)) over (partition by l.vendor, l.ir_ts)) as inv_log_value,
       max({{ as_int('ev.n_change_price > 0') }}) over (partition by l.vendor, l.ir_ts) as inv_any_price_change,
       max({{ as_int('ev.n_change_qty > 0') }}) over (partition by l.vendor, l.ir_ts)   as inv_any_qty_change,
       {{ dow('l.ir_ts') }}                                                        as ir_dow,
       day(l.ir_ts)                                                                as ir_day,
       cast({{ diff_hours('ev.last_gr', 'l.ir_ts') }} as double) / 24              as days_since_gr,
       coalesce(r.vendor_rpb_30d, 0)                                               as vendor_rpb_30d,
       coalesce(r.vendor_ir_30d, 0)                                                as vendor_ir_30d,
       cast(coalesce(r.vendor_rpb_30d, 0) as double) / (coalesce(r.vendor_ir_30d, 0) + 5) as vendor_recent_block_ratio,
       vh.vendor_lines,
       (cast(vh.vendor_blocked as double) + 20 * g.rate) / (vh.vendor_lines + 20)  as vendor_block_rate
from lines l
join ev on ev.case_id = l.case_id
join po on po.po = l.po
left join value_now vn on vn.case_id = l.case_id and vn.rn = 1
left join po_prev pp on pp.case_id = l.case_id
left join recent r on r.case_id = l.case_id
join vendor_hist vh on vh.vendor = l.vendor and vh.at_month = l.cut_month
cross join global_rate g
