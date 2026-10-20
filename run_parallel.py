#!/usr/bin/env python3
"""Independent per-year subprocesses; per-day checkpoints and per-year JSONL."""
import argparse
import concurrent.futures
import datetime as dt
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

LOG=logging.getLogger('parallel')
STOP=threading.Event()
RUNNING=set()
LOCK=threading.Lock()

def signal_stop(signum, frame):
    STOP.set()
    LOG.warning('Interrupt received. Stop jobs; saved daily checkpoints remain reusable.')
    with LOCK:
        procs=list(RUNNING)
    for p in procs:
        if p.poll() is None:
            try: p.terminate()
            except ProcessLookupError: pass

def run_year(year,args):
    if STOP.is_set(): return year,130
    start=max(dt.date(year,1,1),dt.date.fromisoformat(args.start))
    end=min(dt.date(year,12,31),dt.date.fromisoformat(args.end))
    state=Path(args.data_dir)/'state_by_year'/str(year)
    output=Path(args.data_dir)/f'cs_epaper_{year}.jsonl'
    log=Path(args.log_dir)/f'cs_{year}.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable, str(Path(__file__).with_name('cs_epaper.py')),
        '--start',start.isoformat(),'--end',end.isoformat(),
        '--state-dir',str(state),'--output',str(output),
        '--delay',str(args.delay),'--timeout',str(args.timeout),
        '--retries',str(args.retries),'--retry-failed','--incremental']
    if args.force_date: cmd.append('--force-date')
    if args.limit_days: cmd+=['--limit-days',str(args.limit_days)]
    if args.include_disclosure:cmd.append('--include-disclosure')
    LOG.info('START %s %s to %s | %s',year,start,end,output)
    with log.open('a',encoding='utf-8') as f:
        f.write('\n=== NEW RUN '+dt.datetime.now().isoformat()+' ===\n')
        f.flush()
        p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
        with LOCK: RUNNING.add(p)
        try: rc=p.wait()
        finally:
            with LOCK: RUNNING.discard(p)
    LOG.info('END %s rc=%s log=%s',year,rc,log)
    return year,rc

def main():
    ap=argparse.ArgumentParser(description='CS e-paper concurrent year collector')
    ap.add_argument('--start',default='2016-01-01')
    ap.add_argument('--end',default='2024-06-30')
    ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--delay',type=float,default=3)
    ap.add_argument('--timeout',type=float,default=20)
    ap.add_argument('--retries',type=int,default=2)
    ap.add_argument('--data-dir',default='data/raw/cs')
    ap.add_argument('--log-dir',default='logs/cs')
    ap.add_argument('--limit-days',type=int,default=0,help='Maximum newly processed dates PER YEAR')
    ap.add_argument('--force-date',action='store_true',help='Rebuild complete days, use after parser fixes')
    ap.add_argument('--include-disclosure',action='store_true')
    args=ap.parse_args()
    if args.workers<1 or args.workers>12:ap.error('workers must be between 1 and 12')
    if args.delay<0:ap.error('delay must be nonnegative')
    start=dt.date.fromisoformat(args.start);end=dt.date.fromisoformat(args.end)
    if start>end:ap.error('start must precede end')
    years=list(range(start.year,end.year+1))
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    signal.signal(signal.SIGINT,signal_stop)
    signal.signal(signal.SIGTERM,signal_stop)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run_year,y,args) for y in years]
            outcomes=[f.result() for f in futures]
    except KeyboardInterrupt:
        signal_stop(signal.SIGINT,None)
        return 130
    bad=[y for y,rc in outcomes if rc!=0]
    if bad:LOG.warning('Some year processes did not finish: %s',bad)
    return 1 if bad else 0

if __name__=='__main__':sys.exit(main())
