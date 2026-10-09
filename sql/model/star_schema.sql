-- Star schema over the raw Nūs growth tables. Portable between DuckDB (local) and Amazon Athena (Trino):
-- dates come from ISO strings with substr + CAST, and only standard window functions are used.
-- Raw tables (CSV, from extract.py; Athena external tables in sql/athena/00_external_tables.sql):
--   download_snapshots(taken_at, repo, tag, asset, product, kind, download_count, published_at)   cumulative counts, ~every 4h
--   site_daily("day", name, kind, "count")                                                          daily site analytics
--   funnel_events(event_name, event_count, occurred_at)                                          daily funnel counts

-- ---------------------------------------------------------------- dimensions

CREATE OR REPLACE VIEW dim_date AS
WITH days AS (
  SELECT DISTINCT CAST(substr(taken_at, 1, 10) AS DATE) AS d FROM download_snapshots
  UNION SELECT DISTINCT CAST("day" AS DATE) FROM site_daily
  UNION SELECT DISTINCT CAST(substr(occurred_at, 1, 10) AS DATE) FROM funnel_events
)
SELECT
  CAST(replace(CAST(d AS VARCHAR), '-', '') AS INTEGER) AS date_key,
  d AS full_date,
  CAST(date_trunc('week', d) AS DATE) AS week_start,
  date_diff('day', CAST(date_trunc('week', d) AS DATE), d) + 1 AS iso_day_of_week,
  date_diff('day', CAST(date_trunc('week', d) AS DATE), d) >= 5 AS is_weekend
FROM days;

CREATE OR REPLACE VIEW dim_release AS
SELECT
  row_number() OVER (ORDER BY min(published_at), repo, tag) AS release_key,
  repo, tag,
  CAST(substr(min(published_at), 1, 10) AS DATE) AS published_date
FROM download_snapshots
GROUP BY repo, tag;

-- Grain: one row per release file (repo + tag + asset). The same file name ships in several releases and is not
-- always the same product (Nus-Setup.exe is 'legacy' in early releases and 'full' later), so keying on the file
-- name alone would join twice and double-count.
CREATE OR REPLACE VIEW dim_asset AS
SELECT
  row_number() OVER (ORDER BY repo, tag, asset) AS asset_key,
  repo, tag, asset, product, kind,
  CASE WHEN asset LIKE '%.dmg' THEN 'macOS'
       WHEN asset LIKE '%.exe' THEN 'Windows'
       WHEN asset LIKE '%.zip' THEN 'source zip'
       ELSE 'update feed' END AS platform
FROM (SELECT DISTINCT repo, tag, asset, product, kind FROM download_snapshots) a;

CREATE OR REPLACE VIEW dim_page AS
SELECT row_number() OVER (ORDER BY kind, name) AS page_key, name, kind
FROM (SELECT DISTINCT name, kind FROM site_daily) p;

-- ---------------------------------------------------------------- facts

-- Grain: one row per release asset per day (repo + tag + asset: the same file name ships in several releases,
-- so a delta taken per file name alone mixes releases and goes negative).
-- Per day: the cumulative count at the day's last snapshot, and the day's new downloads from LAG.
-- The first day of each asset has no previous count, so its daily_downloads is NULL (unknown), never 0.
CREATE OR REPLACE VIEW fact_downloads_daily AS
WITH last_of_day AS (
  SELECT
    asset, repo, tag,
    CAST(substr(taken_at, 1, 10) AS DATE) AS d,
    download_count,
    row_number() OVER (PARTITION BY repo, tag, asset, substr(taken_at, 1, 10) ORDER BY taken_at DESC) AS rn
  FROM download_snapshots
),
daily AS (
  SELECT asset, repo, tag, d, download_count AS cumulative_downloads FROM last_of_day WHERE rn = 1
)
SELECT
  CAST(replace(CAST(daily.d AS VARCHAR), '-', '') AS INTEGER) AS date_key,
  a.asset_key,
  r.release_key,
  daily.cumulative_downloads,
  daily.cumulative_downloads - lag(daily.cumulative_downloads) OVER (PARTITION BY daily.repo, daily.tag, daily.asset ORDER BY daily.d) AS daily_downloads,
  date_diff('day', r.published_date, daily.d) AS days_since_release
FROM daily
JOIN dim_asset a ON a.repo = daily.repo AND a.tag = daily.tag AND a.asset = daily.asset
JOIN dim_release r ON r.repo = daily.repo AND r.tag = daily.tag;

CREATE OR REPLACE VIEW fact_site_daily AS
SELECT
  CAST(replace(s."day", '-', '') AS INTEGER) AS date_key,
  p.page_key,
  s."count" AS hits
FROM site_daily s
JOIN dim_page p ON p.name = s.name AND p.kind = s.kind;

CREATE OR REPLACE VIEW fact_funnel_daily AS
SELECT
  CAST(replace(substr(occurred_at, 1, 10), '-', '') AS INTEGER) AS date_key,
  event_name,
  sum(event_count) AS events
FROM funnel_events
GROUP BY 1, 2;
