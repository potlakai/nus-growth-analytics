-- Analysis queries over the star schema. Each starts with "-- name: <id>" so analysis/run.py can run them one by one.
-- Portable between DuckDB and Athena.

-- name: q1_daily_installer_downloads
-- New installer downloads per day (update-feed checks excluded: those are existing users, not new ones).
SELECT d.full_date, sum(f.daily_downloads) AS installer_downloads
FROM fact_downloads_daily f
JOIN dim_date d ON d.date_key = f.date_key
JOIN dim_asset a ON a.asset_key = f.asset_key
WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL
GROUP BY d.full_date
ORDER BY d.full_date;

-- name: q2_rolling_7day
-- 7-day rolling average of daily installer downloads.
WITH daily AS (
  SELECT d.full_date, sum(f.daily_downloads) AS downloads
  FROM fact_downloads_daily f
  JOIN dim_date d ON d.date_key = f.date_key
  JOIN dim_asset a ON a.asset_key = f.asset_key
  WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL
  GROUP BY d.full_date
)
SELECT full_date, downloads,
       round(avg(downloads) OVER (ORDER BY full_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS rolling_7d_avg
FROM daily
ORDER BY full_date;

-- name: q3_downloads_by_product_platform
-- Downloads in the observed window by product and platform, with each one's share.
SELECT a.product, a.platform, sum(f.daily_downloads) AS downloads,
       round(100.0 * sum(f.daily_downloads) / sum(sum(f.daily_downloads)) OVER (), 1) AS pct_of_total
FROM fact_downloads_daily f
JOIN dim_asset a ON a.asset_key = f.asset_key
WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL
GROUP BY a.product, a.platform
ORDER BY downloads DESC;

-- name: q4_lifetime_by_release
-- Lifetime installer downloads by release (latest cumulative count per asset, summed).
WITH latest AS (
  SELECT f.asset_key, f.release_key, f.cumulative_downloads,
         row_number() OVER (PARTITION BY f.asset_key, f.release_key ORDER BY f.date_key DESC) AS rn
  FROM fact_downloads_daily f
)
SELECT r.repo, r.tag, r.published_date, sum(l.cumulative_downloads) AS lifetime_downloads
FROM latest l
JOIN dim_release r ON r.release_key = l.release_key
JOIN dim_asset a ON a.asset_key = l.asset_key
WHERE l.rn = 1 AND a.kind = 'installer'
GROUP BY r.repo, r.tag, r.published_date
ORDER BY r.published_date;

-- name: q5_release_age_decay
-- Average daily downloads by release age bucket: how fast does a release's pull decay?
SELECT CASE WHEN f.days_since_release <= 7 THEN '0-7 days'
            WHEN f.days_since_release <= 21 THEN '8-21 days'
            ELSE '22+ days' END AS release_age,
       round(avg(f.daily_downloads), 2) AS avg_daily_downloads_per_asset,
       count(*) AS asset_days
FROM fact_downloads_daily f
JOIN dim_asset a ON a.asset_key = f.asset_key
WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL
GROUP BY 1
ORDER BY min(f.days_since_release);

-- name: q6_traffic_vs_downloads
-- Site visits and installer downloads on the same days (the regression's input).
WITH visits AS (
  SELECT f.date_key, sum(f.hits) AS visits
  FROM fact_site_daily f JOIN dim_page p ON p.page_key = f.page_key
  WHERE p.kind = 'total' AND p.name = 'visits'
  GROUP BY f.date_key
),
downloads AS (
  SELECT f.date_key, sum(f.daily_downloads) AS downloads
  FROM fact_downloads_daily f JOIN dim_asset a ON a.asset_key = f.asset_key
  WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL
  GROUP BY f.date_key
)
SELECT d.full_date, d.is_weekend, coalesce(v.visits, 0) AS visits, dl.downloads
FROM downloads dl
JOIN dim_date d ON d.date_key = dl.date_key
LEFT JOIN visits v ON v.date_key = dl.date_key
ORDER BY d.full_date;

-- name: q7_site_funnel
-- The site funnel over the whole window: each stage and its conversion from the stage before.
WITH stages AS (
  SELECT event_name, sum(events) AS n,
         CASE event_name WHEN 'landing_view' THEN 1 WHEN 'download_click' THEN 2 WHEN 'install' THEN 3
                         WHEN 'app_open' THEN 4 WHEN 'first_ask' THEN 5 WHEN 'signin' THEN 6 END AS stage
  FROM fact_funnel_daily GROUP BY event_name
)
SELECT stage, event_name, n,
       round(100.0 * n / lag(n) OVER (ORDER BY stage), 1) AS pct_of_previous,
       round(100.0 * n / first_value(n) OVER (ORDER BY stage), 1) AS pct_of_landing
FROM stages
WHERE stage IS NOT NULL
ORDER BY stage;

-- name: q8_download_buttons
-- Which site download buttons get clicked (event names), ranked.
SELECT p.name AS button, sum(f.hits) AS clicks
FROM fact_site_daily f JOIN dim_page p ON p.page_key = f.page_key
WHERE p.kind = 'event' AND p.name LIKE 'download-%'
GROUP BY p.name
ORDER BY clicks DESC;
