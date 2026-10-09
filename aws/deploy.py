"""S3 + Athena deployment through the AWS CLI (no extra Python packages).

What it does, in order:
  1. creates the bucket if it does not exist (private; block-public-access stays on by default for new buckets),
  2. uploads data/raw/*.csv, one folder per table, as sql/athena/00_external_tables.sql expects,
  3. runs the external-table DDL, then sql/model/star_schema.sql unchanged, then every query in sql/analysis/queries.sql,
  4. writes docs/athena-results.md so the answers can be compared with docs/results.md (DuckDB).
Usage: python aws/deploy.py --bucket <name> --profile pranav --region us-east-2
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def aws(args, profile, region, parse=True):
    cmd = ['aws', *args, '--profile', profile, '--region', region, '--output', 'json']
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise SystemExit(f"aws {' '.join(args[:3])} failed:\n{r.stderr.strip()}")
    return json.loads(r.stdout) if parse and r.stdout.strip() else r.stdout


def ensure_bucket(bucket, profile, region):
    r = subprocess.run(['aws', 's3api', 'head-bucket', '--bucket', bucket, '--profile', profile, '--region', region], capture_output=True, text=True)
    if r.returncode == 0:
        print(f'bucket {bucket}: exists')
        return
    args = ['s3api', 'create-bucket', '--bucket', bucket]
    if region != 'us-east-1':
        args += ['--create-bucket-configuration', f'LocationConstraint={region}']
    aws(args, profile, region)
    aws(['s3api', 'put-public-access-block', '--bucket', bucket, '--public-access-block-configuration',
         'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'], profile, region, parse=False)
    print(f'bucket {bucket}: created, public access blocked')


def upload(bucket, profile, region):
    for table in ('download_snapshots', 'site_daily', 'funnel_events'):
        src = ROOT / 'data' / 'raw' / f'{table}.csv'
        dest = f's3://{bucket}/nus-growth/raw/{table}/{table}.csv'
        subprocess.run(['aws', 's3', 'cp', str(src), dest, '--profile', profile, '--region', region], check=True)
    print('uploaded 3 CSVs')


def statements(sql):
    """Statements of a SQL file, comments stripped, split on ';'."""
    body = '\n'.join(l for l in sql.splitlines() if not l.strip().startswith('--'))
    return [s.strip() for s in body.split(';') if s.strip()]


def run_query(sql, database, output, profile, region):
    q = aws(['athena', 'start-query-execution', '--query-string', sql, '--work-group', 'primary',
             '--result-configuration', f'OutputLocation={output}', *(['--query-execution-context', f'Database={database}'] if database else [])],
            profile, region)
    qid = q['QueryExecutionId']
    while True:
        e = aws(['athena', 'get-query-execution', '--query-execution-id', qid], profile, region)['QueryExecution']
        state = e['Status']['State']
        if state in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            break
        time.sleep(1.5)
    if state != 'SUCCEEDED':
        raise SystemExit(f"Athena {state}: {e['Status'].get('StateChangeReason', '')}\n--- statement ---\n{sql[:600]}")
    return qid


def results(qid, profile, region):
    r = aws(['athena', 'get-query-results', '--query-execution-id', qid], profile, region)
    rows = [[c.get('VarCharValue', '') for c in row['Data']] for row in r['ResultSet']['Rows']]
    return rows[0], rows[1:]


def table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    lines += ['| ' + ' | '.join(r) + ' |' for r in rows]
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bucket', required=True)
    ap.add_argument('--profile', default='pranav')
    ap.add_argument('--region', default='us-east-2')
    ap.add_argument('--skip-upload', action='store_true')
    a = ap.parse_args()
    output = f's3://{a.bucket}/athena-results/'

    ensure_bucket(a.bucket, a.profile, a.region)
    if not a.skip_upload:
        upload(a.bucket, a.profile, a.region)

    ddl = (ROOT / 'sql' / 'athena' / '00_external_tables.sql').read_text(encoding='utf-8').replace('<bucket>', a.bucket)
    for s in statements(ddl):
        run_query(s, None, output, a.profile, a.region)
    print('external tables: ok')

    # OpenCSVSerde reads every column as a string; the one integer column it feeds is cast here, the rest of the model runs unchanged.
    model = (ROOT / 'sql' / 'model' / 'star_schema.sql').read_text(encoding='utf-8').replace('s."count" AS hits', 'CAST(s."count" AS INTEGER) AS hits')
    for s in statements(model):
        run_query(s, 'nus_growth', output, a.profile, a.region)
    print('star schema views: ok')

    text = (ROOT / 'sql' / 'analysis' / 'queries.sql').read_text(encoding='utf-8')
    out = ['# Athena results (generated by aws/deploy.py)', '', f'Bucket `{a.bucket}`, region `{a.region}`, database `nus_growth`. Compare with docs/results.md (DuckDB): the numbers must match.', '']
    for block in re.split(r'(?m)^-- name: ', text)[1:]:
        name, sql = block.split('\n', 1)
        qid = run_query(statements(sql)[0], 'nus_growth', output, a.profile, a.region)
        header, rows = results(qid, a.profile, a.region)
        out += [f'## {name.strip()}', '', table(header, rows), '']
        print(f'{name.strip()}: {len(rows)} rows')
    (ROOT / 'docs' / 'athena-results.md').write_text('\n'.join(out), encoding='utf-8')
    print('wrote docs/athena-results.md')


if __name__ == '__main__':
    sys.exit(main())
