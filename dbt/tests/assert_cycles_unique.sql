select case_id, cycle_no, count(*) as n from {{ ref('cycles') }} group by case_id, cycle_no having count(*) > 1
