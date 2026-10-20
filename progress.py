#!/usr/bin/env python3
"""Read-only progress monitor for yearly CS e-paper checkpoints."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import time

VALID={'complete','partial','failed','unavailable','not_published','network_error','template_error'}

def snapshot(data_dir,start,end):
    a=date.fromisoformat(start); b=date.fromisoformat(end)
    total=(b-a).days+1
    years={}
    for yr in range(a.year,b.year+1):
        lo=max(a,date(yr,1,1)); hi=min(b,date(yr,12,31))
        rec={'year':yr,'total':(hi-lo).days+1,'attempted':0,'complete':0,'articles':0,'failures':0,'statuses':Counter(),'last_date':'—'}
        folder=Path(data_dir)/'state_by_year'/str(yr)
        for p in folder.glob('????-??-??.json'):
            try:
                day=date.fromisoformat(p.stem)
                if not lo<=day<=hi: continue
                d=json.loads(p.read_text(encoding='utf-8'))
                status=d.get('status','unknown')
                rec['statuses'][status]+=1
                rec['attempted']+=1
                rec['complete']+=status=='complete'
                rec['articles']+=len(d.get('articles') or [])
                rec['failures']+=int(d.get('failed_count') or 0)
                rec['last_date']=max(rec['last_date'],p.stem) if rec['last_date']!='—' else p.stem
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                rec['statuses']['bad_state']+=1
        years[yr]=rec
    return years,total

def bar(n,total,width=22):
    frac=(n/total) if total else 0
    filled=min(width,round(frac*width))
    return '█'*filled+'░'*(width-filled)

def render(data_dir,start,end):
    years,total=snapshot(data_dir,start,end)
    attempted=sum(r['attempted'] for r in years.values())
    complete=sum(r['complete'] for r in years.values())
    articles=sum(r['articles'] for r in years.values())
    partial=sum(r['statuses']['partial'] for r in years.values())
    fail=sum(r['statuses']['failed']+r['statuses']['network_error']+r['statuses']['template_error'] for r in years.values())
    unavailable=sum(r['statuses']['unavailable'] for r in years.values())
    print('中国证券报电子报采集进度（读取当前状态文件，不发网络请求）')
    print(f'总体处理：{bar(attempted,total)} {attempted}/{total} 天 ({attempted/total:.1%})')
    print(f'完整日期：{bar(complete,total)} {complete}/{total} 天 ({complete/total:.1%})')
    print(f'已保存文章：{articles:,} 篇 | partial：{partial} 天 | failed：{fail} 天 | unavailable：{unavailable} 天')
    print('年份   已处理/区间天数   完整   部分   失败   不可用   文章数     最近状态日期')
    for y,r in years.items():
        s=r['statuses']
        print(f"{y}   {r['attempted']:>3}/{r['total']:<3}          {r['complete']:>3}    {s['partial']:>3}    {s['failed']:>3}    {s['unavailable']:>3}     {r['articles']:>7,}   {r['last_date']}")
    print('说明：已处理含partial/failed/unavailable，不能代表数据完整；现有旧状态也计入。')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-dir',default='data/raw/cs')
    ap.add_argument('--start',default='2016-01-01')
    ap.add_argument('--end',default='2024-06-30')
    ap.add_argument('--watch',type=float,default=0,help='每隔N秒刷新，0表示仅显示一次')
    args=ap.parse_args()
    if args.watch<0:ap.error('--watch must be >= 0')
    try:
        while True:
            if args.watch:print('\033[2J\033[H',end='')
            render(args.data_dir,args.start,args.end)
            if not args.watch:break
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print('\n监控已停止，采集进程不受影响。')

if __name__=='__main__':main()
