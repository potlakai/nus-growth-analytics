# Walkthrough: what to be able to say in an interview

Read this, run every step yourself once, and change one query on purpose to see what breaks. If you can't explain a line, ask Claude before you put it on a resume.

## 1. Extract (`extract.py`)

- Reads `growth.db` read-only.
- Writes 3 CSVs.
- Strips query strings from page paths, because they carried signed attribution tokens.

**Why it matters:** never ship secrets or PII into a data lake.

## 2. Star schema (`sql/model/star_schema.sql`)

- **Facts** are the things you count: downloads per release file per day, site hits, funnel events.
- **Dimensions** are what you slice by: date, release, asset, page.
- **The key SQL:** `row_number() OVER (PARTITION BY repo, tag, asset, day ORDER BY taken_at DESC)` picks each day's last snapshot. Then `cumulative - LAG(cumulative) OVER (PARTITION BY repo, tag, asset ORDER BY day)` gives the day's new downloads.

**Two bugs the data exposed, and how you fixed them:**
1. Deltas by file name alone went negative, because the same file name appears in several releases. The fix was to partition by release and file.
2. A file name mapped to two products. Joining the dimension on name alone duplicated rows. The fix was to key the dimension on repo + tag + asset.

3. The daily series disagreed between DuckDB and Athena. DuckDB had parsed the timestamps as timezone-aware and printed them in local time, shifting early-UTC snapshots a day back. The fix was to load timestamps as text. Running the same SQL on two engines is what exposed it.

**The interview line:** "I check grain first: what is one row? Then I check the same answer two ways."

## 3. Queries (`sql/analysis/queries.sql`)

| Query | What it shows |
|---|---|
| q1 | Daily downloads |
| q2 | 7-day rolling average (`AVG ... ROWS BETWEEN 6 PRECEDING AND CURRENT ROW`) |
| q3 | Share by product and platform (`SUM(...) OVER ()` for the denominator) |
| q4 | Lifetime by release (latest row per key via `row_number`) |
| q5 | Release-age buckets (`CASE`) |
| q6 | Traffic vs downloads (`LEFT JOIN`) |
| q7 | Funnel conversion (`LAG` and `FIRST_VALUE`) |
| q8 | Top download buttons |

## 4. Statistics (`analysis/run.py`)

**Release-decay regression (OLS):**
- Model: daily downloads ~ log(1 + days since release) + product.
- Why log: decay is fast at first and then flattens.
- Why robust (HC1) errors: the variance is bigger early in a release's life.
- How to read the coefficient: -1.17 with p = 0.004 means each unit increase in log-age cuts expected daily downloads by about 1.2 per file.
- Business action: ship releases on a cadence, because each one restarts the pull.
- R² is low (0.06), and that's fine: the question is direction and significance, not prediction.

**Chi-square (2x2):**
- Compares organic vs paid profile visits per impression.
- Organic converts 5.5x better, p < 0.001.
- Caveat: the source panel is inconsistent, so treat it as directional.

**Welch t-test:**
- Weekday vs weekend daily downloads.
- No detectable difference (p = 0.49, only 3 weekend days).
- Welch, because the groups have unequal size and variance.

## 5. Data-quality judgment

**Zeros before 2026-10-06 are missing data, not zero traffic.** The regression on visits was dropped rather than run on fake zeros. Interviewers value this more than a fancy model.
