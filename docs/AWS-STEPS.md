# Your part: S3, Athena, QuickSight (about 2-3 hours)

Do these yourself in your own AWS account. That's what makes "S3 / Athena / QuickSight" true on the resume, and it's what you'll describe in the interview. Never paste keys into chat or into this repo.

## 1. S3 (15 min)

1. Sign in to the AWS console. Use the free tier, and set a $5 budget alert under Billing → Budgets.
2. Create an S3 bucket, for example `pranav-nus-growth`, in us-east-1, with all public access blocked.
3. Upload each CSV in `data/raw/` into its own folder:
   - `nus-growth/raw/download_snapshots/`
   - `nus-growth/raw/site_daily/`
   - `nus-growth/raw/funnel_events/`

## 2. Athena (45 min)

1. In Athena settings, set the query result location to `s3://<bucket>/athena-results/`.
2. Run `sql/athena/00_external_tables.sql` (replace `<bucket>` first).
3. Run `sql/model/star_schema.sql`. It's the same file DuckDB runs locally.
4. Run each query in `sql/analysis/queries.sql`. Check every answer against `docs/results.md`. If one differs, find out why: that's the debugging story for your interview.
5. Screenshot one query and its result for the README.

## 3. QuickSight (1-1.5 hours)

1. Sign up for QuickSight (free trial) and give it access to the S3 bucket and to Athena.
2. Create datasets from Athena: `fact_downloads_daily` joined to `dim_date`, `dim_asset` and `dim_release`; and `fact_funnel_daily`.
3. Build one dashboard with:
   - **KPI row:** downloads in the window, new downloads in the last 7 days, the companion's share.
   - **Line chart:** daily installer downloads with a 7-day rolling average (q2).
   - **Bar chart:** downloads by product and platform (q3).
   - **Bar chart:** average daily downloads by release-age bucket (q5). This is the release-decay finding.
   - **Funnel:** landing_view → download_click → install → app_open → first_ask → signin (q7).
4. Publish it. Screenshot it to `docs/quicksight-dashboard.png`.

## 4. Tell Claude when it's done

Claude then adds the project to the README and the resume bullet, rebuilds the Amazon PDF, and pins the repo once you okay pushing it.
