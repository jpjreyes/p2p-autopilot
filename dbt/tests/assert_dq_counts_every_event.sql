-- Nothing is silently dropped: the event log has exactly the rows that were landed.
select d.n, s.n_source
from {{ ref('dq_report') }} d
cross join (select count(*) as n_source from {{ ref('stg_sap_events') }}) s
where d.check_name = 'events_total' and d.n <> s.n_source
