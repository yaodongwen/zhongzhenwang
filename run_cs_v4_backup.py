#!/usr/bin/env python3
"""Single safe entrypoint: URL repair (default), date crawling, or both.
Existing project scripts and their arguments remain usable; this is additive.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def run(cmd):
    print('RUN:', ' '.join(map(str,cmd)), flush=True)
    subprocess.run(cmd, check=True)


def main():
    p=argparse.ArgumentParser(description='Chinese Securities Journal unified crawl/recovery launcher')
    p.add_argument('--start',default='2016-01-01')
    p.add_argument('--end',default='2024-06-30')
    p.add_argument('--mode',choices=('repair','crawl','all','audit'),default='repair',
                   help='repair=known URLs only (default); crawl=discover dates; all=crawl then repair; audit=offline')
    p.add_argument('--workers',type=int,default=2,help='Used by crawl phase only; URL repair is serial')
    p.add_argument('--delay',type=float,default=2.0)
    p.add_argument('--timeout',type=float,default=25)
    p.add_argument('--retries',type=int,default=2)
    p.add_argument('--limit-urls',type=int,default=100,help='0=all eligible URLs')
    p.add_argument('--types',nargs='+',default=['legacy_title','http_5xx','ssl','timeout','connection','rate_limit'])
    p.add_argument('--data-dir',default='data/raw/cs')
    p.add_argument('--qc-dir',default='data/qc/cs_recovery')
    p.add_argument('--log-dir',default='logs/cs')
    p.add_argument('--progress-interval',type=float,default=10,help='Crawl phase refresh interval')
    p.add_argument('--progress-every',type=int,default=5,help='Repair phase prints progress every N URLs')
    p.add_argument('--dry-run',action='store_true',help='Repair mode only; do not fetch or modify')
    args=p.parse_args()
    try:
        start=dt.date.fromisoformat(args.start);end=dt.date.fromisoformat(args.end)
    except ValueError as e:p.error(str(e))
    if start>end:p.error('start after end')
    if args.delay<0 or args.limit_urls<0 or args.progress_every<1:p.error('invalid delay/limit/progress-every')
    years=[str(y) for y in range(start.year,end.year+1)]
    state_root=Path(args.data_dir)/'state_by_year'
    qc=Path(args.qc_dir)
    if args.mode in ('crawl','all'):
        if args.dry_run:p.error('--dry-run is not compatible with crawl/all')
        if not Path('run_parallel.py').is_file():p.error('missing run_parallel.py in project root')
        run([sys.executable,'run_parallel.py','--start',args.start,'--end',args.end,
             '--workers',str(args.workers),'--delay',str(args.delay),
             '--timeout',str(args.timeout),'--retries',str(args.retries),
             '--data-dir',args.data_dir,'--log-dir',args.log_dir,
             '--progress-interval',str(args.progress_interval)])
    if args.mode in ('repair','all','audit'):
        for file in ('audit_unresolved.py','repair_urls.py','cs_epaper.py'):
            if not Path(file).is_file():p.error(f'missing {file} in project root')
        for y in years:
            state=state_root/y
            if not state.is_dir() or not next(state.glob(f'{y}-??-??.json'),None):
                p.error(f'{state}: no daily checkpoint; cannot safely repair from annual JSONL alone. '
                        'Migrate/verify checkpoints first.')
        qc.mkdir(parents=True,exist_ok=True)
        run([sys.executable,'audit_unresolved.py','--state-root',str(state_root),
             '--years',*years,'--out-dir',str(qc)])
        if args.mode=='audit':return 0
        summary_path=qc/'summary.json'
        summary=json.loads(summary_path.read_text(encoding='utf-8'))
        print('AUDIT CANDIDATES:',summary.get('candidate_urls_for_review'),
              '(historical candidates, not confirmed missing news)',flush=True)
        cmd=[sys.executable,'repair_urls.py','--candidate-csv',str(qc/'candidate_urls_review.csv'),
             '--state-root',str(state_root),'--output-dir',args.data_dir,
             '--years',*years,'--types',*args.types,
             '--limit-urls',str(args.limit_urls),'--delay',str(args.delay),
             '--timeout',str(args.timeout),'--retries',str(args.retries),
             '--progress-every',str(args.progress_every)]
        if args.dry_run:cmd.append('--dry-run')
        run(cmd)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f'FAILED: subprocess exit code {e.returncode}; previously saved checkpoints remain on disk',file=sys.stderr)
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print('\nInterrupted; already written checkpoints are retained.',file=sys.stderr)
        sys.exit(130)
