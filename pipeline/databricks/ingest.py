"""Job task 2 (Databricks): Auto Loader picks up only the files that arrived since the last run and appends them to
the bronze table, every column as text plus the source file. Incremental ingestion with exactly-once file tracking
(the checkpoint), run as a batch (availableNow), not a stream: the extract arrives once a day.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

spark = SparkSession.builder.getOrCreate()
RAW = "workspace.p2p_autopilot_raw"
COLUMNS = ["file_row", "extract_date", "case_id", "activity", "timestamp", "resource", "user", "cum_net_worth_eur",
           "event_id", "case_purchasing_document", "case_item", "case_item_type", "case_item_category",
           "case_gr_based_inv_verif", "case_goods_receipt", "case_source", "case_purch_doc_category_name",
           "case_company", "case_spend_classification_text", "case_spend_area_text", "case_sub_spend_area_text",
           "case_vendor", "case_name", "case_document_type"]
schema = StructType([StructField(c, StringType()) for c in COLUMNS])
before = spark.sql(f"SELECT count(*) AS n FROM {RAW}.sap_events").first()["n"] \
    if spark.catalog.tableExists(f"{RAW}.sap_events") else 0
q = (spark.readStream.format("cloudFiles")
     .option("cloudFiles.format", "csv").option("header", "true")
     .option("pathGlobFilter", "sap_events_*.csv.gz")
     .schema(schema)
     .load("/Volumes/workspace/p2p_autopilot_raw/landing/")
     .withColumn("source_file", F.col("_metadata.file_name"))
     .writeStream
     .option("checkpointLocation", "/Volumes/workspace/p2p_autopilot_raw/checkpoints/bronze_sap_events")
     .trigger(availableNow=True)
     .toTable(f"{RAW}.sap_events"))
q.awaitTermination()
after = spark.sql(f"SELECT count(*) AS n FROM {RAW}.sap_events").first()["n"]
dupes = spark.sql(f"SELECT count(*) - count(DISTINCT file_row) AS d FROM {RAW}.sap_events").first()["d"]
print(f"bronze: {before:,} -> {after:,} rows (+{after - before:,}); duplicate source rows: {dupes}")
if dupes:
    raise SystemExit("a landed file was ingested twice")
