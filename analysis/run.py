"""Builds the star schema in DuckDB from data/raw, runs every analysis query, and runs the statistics.

Outputs: data/model/*.csv (the star schema tables, ready for QuickSight), docs/results.md, docs/*.png.
Usage: .venv/Scripts/python analysis/run.py
"""
from pathlib import Path
import re

import duckdb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
RAW, MODEL, DOCS = ROOT / 'data' / 'raw', ROOT / 'data' / 'model', ROOT / 'docs'
STAR = ['dim_date', 'dim_release', 'dim_asset', 'dim_page', 'fact_downloads_daily', 'fact_site_daily', 'fact_funnel_daily']


def build(con):
    for table in ('download_snapshots', 'site_daily', 'funnel_events'):
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{(RAW / (table + '.csv')).as_posix()}', all_varchar=false)")
    # The CSVs hold ISO strings; keep the timestamp columns as text so the SQL stays portable to Athena.
    con.execute("CREATE OR REPLACE TABLE download_snapshots AS SELECT CAST(taken_at AS VARCHAR) taken_at, repo, tag, asset, product, kind, "
                "CAST(download_count AS INTEGER) download_count, CAST(published_at AS VARCHAR) published_at FROM download_snapshots")
    con.execute('CREATE OR REPLACE TABLE site_daily AS SELECT CAST("day" AS VARCHAR) AS "day", name, kind, CAST("count" AS INTEGER) AS "count" FROM site_daily')
    con.execute("CREATE OR REPLACE TABLE funnel_events AS SELECT event_name, CAST(event_count AS INTEGER) event_count, CAST(occurred_at AS VARCHAR) occurred_at FROM funnel_events")
    con.execute((ROOT / 'sql' / 'model' / 'star_schema.sql').read_text(encoding='utf-8'))
    MODEL.mkdir(parents=True, exist_ok=True)
    for t in STAR:
        con.execute(f"COPY (SELECT * FROM {t}) TO '{(MODEL / (t + '.csv')).as_posix()}' (HEADER, DELIMITER ',')")


def queries(con):
    text = (ROOT / 'sql' / 'analysis' / 'queries.sql').read_text(encoding='utf-8')
    out = {}
    for block in re.split(r'(?m)^-- name: ', text)[1:]:
        name, sql = block.split('\n', 1)
        out[name.strip()] = con.execute(sql).df()
    return out


def regression(df):
    """OLS: daily installer downloads on site visits and a weekend flag. Small n: read it as direction, not proof."""
    df = df.copy()
    df['weekend'] = df['is_weekend'].astype(int)
    model = smf.ols('downloads ~ visits + weekend', data=df).fit()
    return model


def release_decay(con):
    """OLS at the release-asset-day grain: daily downloads on log(1 + days since release), controlling for product.
    The business question: how fast does a release's pull fade, i.e. how often is a new release worth shipping?"""
    df = con.execute("""
        SELECT f.daily_downloads AS downloads, f.days_since_release AS age, a.product
        FROM fact_downloads_daily f JOIN dim_asset a ON a.asset_key = f.asset_key
        WHERE a.kind = 'installer' AND f.daily_downloads IS NOT NULL AND f.days_since_release >= 0
    """).df()
    df['log_age'] = np.log1p(df['age'])
    return smf.ols('downloads ~ log_age + C(product)', data=df).fit(cov_type='HC1'), len(df)


def paid_vs_organic():
    """Chi-square test of independence on the X campaign's post #3: profile visits per impression, paid vs organic.
    Source: ventures/nus/receipts/x-teardown-2026-07-26.md (X analytics panel; the receipt flags the panel as internally
    inconsistent, so treat the result as directional)."""
    organic_imp, organic_visits = 1735, 28
    paid_imp, paid_visits = 7558 - 1735, 45 - 28
    table = np.array([[organic_visits, organic_imp - organic_visits], [paid_visits, paid_imp - paid_visits]])
    chi2, p, dof, _ = stats.chi2_contingency(table)
    return {'organic_rate': organic_visits / organic_imp, 'paid_rate': paid_visits / paid_imp, 'chi2': chi2, 'p': p, 'dof': dof,
            'lift': (organic_visits / organic_imp) / (paid_visits / paid_imp)}


def weekend_ttest(df):
    """Welch t-test: daily installer downloads on weekdays vs weekends."""
    wk, we = df.loc[~df['is_weekend'], 'downloads'], df.loc[df['is_weekend'], 'downloads']
    t, p = stats.ttest_ind(wk, we, equal_var=False)
    return {'weekday_mean': wk.mean(), 'weekend_mean': we.mean(), 'n_weekday': len(wk), 'n_weekend': len(we), 't': t, 'p': p}


def charts(results):
    DOCS.mkdir(exist_ok=True)
    roll = results['q2_rolling_7day']
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(roll['full_date'].astype(str), roll['downloads'], color='#9bb7d4', label='daily installer downloads')
    ax.plot(roll['full_date'].astype(str), roll['rolling_7d_avg'], color='#1f4e79', marker='o', label='7-day rolling average')
    ax.set_title('Nūs installer downloads per day'); ax.legend(frameon=False); ax.tick_params(axis='x', rotation=60, labelsize=7)
    fig.tight_layout(); fig.savefig(DOCS / 'downloads_daily.png', dpi=150); plt.close(fig)
    # No traffic-vs-downloads chart until 30+ tracked days exist (see the data-quality note in results.md).


def main():
    con = duckdb.connect()
    build(con)
    results = queries(con)
    tv = results['q6_traffic_vs_downloads']
    tracked = tv[tv['full_date'] >= tv.loc[tv['visits'] > 0, 'full_date'].min()] if (tv['visits'] > 0).any() else tv.iloc[0:0]
    decay, decay_n = release_decay(con)
    chi = paid_vs_organic()
    tt = weekend_ttest(tv)
    charts(results)
    sizes = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in STAR}
    lines = ['# Results (generated by analysis/run.py)', '', '## Star schema row counts', '']
    lines += [f'- `{t}`: {n}' for t, n in sizes.items()]
    for name, df in results.items():
        lines += ['', f'## {name}', '', df.to_markdown(index=False)]
    first = tv.loc[tv['visits'] > 0, 'full_date'].min()
    lines += ['', '## Data quality: site visits', '',
              f"Site visits read 0 on every day before {str(first)[:10]}: analytics tracking went live then, so earlier zeros are missing "
              f"data, not zero traffic. Only {len(tracked)} days overlap with download data, too few for a traffic-to-downloads regression; "
              'it is re-run once 30+ tracked days exist (`regression()` is kept for that).',
              '', '## Regression: release decay (release-asset-day grain, robust HC1 errors)', '', '```', str(decay.summary()), '```',
              '', f"n = {decay_n} asset-days. Coefficient on log(1 + days since release): {decay.params['log_age']:.3f} "
              f"(p = {decay.pvalues['log_age']:.2g}); R² = {decay.rsquared:.3f}.",
              '', '## Chi-square: X post #3 profile-visit rate, organic vs paid', '',
              f"Organic {chi['organic_rate']:.2%} vs paid {chi['paid_rate']:.2%} ({chi['lift']:.1f}x); chi² = {chi['chi2']:.1f}, dof = {chi['dof']}, p = {chi['p']:.2g}. "
              'Directional: the X panel this comes from is internally inconsistent (see the receipt).',
              '', '## Welch t-test: weekday vs weekend downloads', '',
              f"Weekday mean {tt['weekday_mean']:.1f} (n={tt['n_weekday']}) vs weekend {tt['weekend_mean']:.1f} (n={tt['n_weekend']}); t = {tt['t']:.2f}, p = {tt['p']:.3f}."]
    (DOCS / 'results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[-12:]))


if __name__ == '__main__':
    main()
