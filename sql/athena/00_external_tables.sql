-- Amazon Athena: external tables over the CSVs in S3, then run sql/model/star_schema.sql unchanged.
-- Replace <bucket> with your bucket name. Upload layout (one folder per table, as Athena expects):
--   s3://<bucket>/nus-growth/raw/download_snapshots/download_snapshots.csv
--   s3://<bucket>/nus-growth/raw/site_daily/site_daily.csv
--   s3://<bucket>/nus-growth/raw/funnel_events/funnel_events.csv

CREATE DATABASE IF NOT EXISTS nus_growth;

CREATE EXTERNAL TABLE IF NOT EXISTS nus_growth.download_snapshots (
  taken_at string, repo string, tag string, asset string, product string, kind string, download_count int, published_at string
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION 's3://<bucket>/nus-growth/raw/download_snapshots/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS nus_growth.site_daily (
  `day` string, name string, kind string, `count` int
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://<bucket>/nus-growth/raw/site_daily/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS nus_growth.funnel_events (
  event_name string, event_count int, occurred_at string
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION 's3://<bucket>/nus-growth/raw/funnel_events/'
TBLPROPERTIES ('skip.header.line.count' = '1');

-- Note: OpenCSVSerde reads every column as string, so in Athena cast site_daily."count" in star_schema.sql if a
-- query complains (CAST(s."count" AS INTEGER)). Then: select the nus_growth database and run star_schema.sql,
-- then any query from sql/analysis/queries.sql. Compare the answers with docs/results.md (they must match).
