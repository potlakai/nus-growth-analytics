"""Extract: read the Nūs growth database (read-only) and write sanitized CSVs to data/raw/.

Sanitizing: page paths lose their query strings (they carry signed attribution tokens and one-time codes), and no
table with free text or personal data is exported. These CSVs are what gets uploaded to S3.
Usage: python extract.py path/to/growth.db   (or set GROWTH_DB)
"""
import csv
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
TABLES = {
    'download_snapshots': 'SELECT taken_at, repo, tag, asset, product, kind, download_count, published_at FROM download_snapshots ORDER BY taken_at, asset',
    'site_daily': 'SELECT day, name, kind, count FROM site_daily ORDER BY day, kind, name',
    'funnel_events': 'SELECT event_name, event_count, occurred_at FROM events ORDER BY occurred_at',
}


def clean_path(name, kind):
    """A page path without its query string; events and totals pass through."""
    return name.split('?', 1)[0] if kind == 'page' else name


def extract(db):
    out = ROOT / 'data' / 'raw'
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    counts = {}
    for table, sql in TABLES.items():
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if table == 'site_daily':
            merged = {}
            for day, name, kind, count in rows:
                key = (day, clean_path(name, kind), kind)
                merged[key] = merged.get(key, 0) + count
            rows = [(*k, v) for k, v in sorted(merged.items())]
        with open(out / f'{table}.csv', 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        counts[table] = len(rows)
    con.close()
    return counts


if __name__ == '__main__':
    source = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('GROWTH_DB')
    if not source:
        sys.exit('Give the path to growth.db (argument or GROWTH_DB).')
    db = Path(source)
    for table, n in extract(db).items():
        print(f'{table}: {n} rows -> data/raw/{table}.csv')
