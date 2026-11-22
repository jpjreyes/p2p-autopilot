-- Rows a retrain may use, as of the data landed so far (D18 label delay, data-layer decision 4):
--   1. the 60-day outcome must be observable: invoice + horizon falls before the end of the last landed day;
--   2. nothing from the test months (>= test_start) ever trains: those months are only scored, in replay too.
with as_of as (
    select max(cast(extract_date as date)) as data_as_of from {{ ref('stg_sap_events') }}
)
select f.*, a.data_as_of
from {{ ref('invoice_features') }} f
cross join as_of a
where {{ add_days('f.ir_ts', var('horizon_days')) }} < {{ add_days('cast(a.data_as_of as timestamp)', 1) }}
  and f.ir_ts < {{ ts_lit(var('test_start')) }}
