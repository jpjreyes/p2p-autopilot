-- Fails the build if a training row's 60-day outcome was not yet observable in the landed data (D18 label delay).
select case_id, ir_ts, data_as_of from {{ ref('training_rows') }}
where {{ add_days('ir_ts', var('horizon_days')) }} >= {{ add_days('cast(data_as_of as timestamp)', 1) }}
