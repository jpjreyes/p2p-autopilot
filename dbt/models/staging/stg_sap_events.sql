-- Types and hidden nulls (D5, D6). The land step's file_row becomes the stable event_id (D7).
select
    cast(file_row as bigint)                                    as event_id,
    case_id,
    activity,
    {{ raw_col('timestamp') }}                            as ts_text,
    {{ ts_from_text(raw_col('timestamp')) }}              as ts_original,
    nullif(resource, 'NONE')                                    as resource,
    nullif({{ raw_col('user') }}, 'NONE')                 as user_id,
    try_cast(cum_net_worth_eur as double)                       as value_eur,
    case_purchasing_document, case_item, case_item_category, case_item_type, case_vendor, case_company,
    case_spend_area_text, case_sub_spend_area_text, case_document_type, case_gr_based_inv_verif, case_goods_receipt,
    extract_date
from {{ source('raw', 'sap_events') }}
