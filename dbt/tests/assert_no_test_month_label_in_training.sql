-- Fails the build if any row from the test months can reach training (data-layer decision 4).
select case_id, ir_ts from {{ ref('training_rows') }} where ir_ts >= {{ ts_lit(var('test_start')) }}
