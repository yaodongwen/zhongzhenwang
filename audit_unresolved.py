#!/usr/bin/env python3
"""Read-only recovery audit for CS epaper state_by_year and historical failure logs."""
import argparse,csv,json,re
from collections import Counter,defaultdict
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

DATE_RE=re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')

def canon(u):
    if not isinstance(u,str):return ''
    # Accept copied markdown links (not produced by crawler, but harmless).
    m=re.fullmatch(r'\[https?://[^\]]+\]\((https?://[^)]+)\)',u)
    if m:u=m.group(1)
    p=urlsplit(u)
    if not p.scheme or not p.netloc:return ''
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,'',''))

def cat(err):
    e=str(err or '').lower()
    if 'missing #div_title' in e:return 'legacy_title'
    if 'missing article title' in e:return 'title_parse'
    if '404' in e:return 'http_404'
    if '403' in e or '429' in e:return 'rate_limit'
    if '502' in e or '503' in e or '504' in e:return 'http_5xx'
    if 'ssl' in e:return 'ssl'
    if 'timeout' in e or 'timed out' in e:return 'timeout'
    if 'no article links found' in e:return 'index_parse'
    if 'body too short' in e:return 'short_body'
    if 'connection' in e or 'incompleteread' in e:return 'connection'
    return 'other'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--state-root',default='data/raw/cs/state_by_year')
    ap.add_argument('--years',nargs='+',type=int,default=[2016,2017])
    ap.add_argument('--out-dir',default='data/qc/cs_recovery')
    args=ap.parse_args()
    root=Path(args.state_root);out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    rows=[]; days=[]
    for y in args.years:
        folder=root/str(y)
        if not folder.exists():
            print('MISSING STATE FOLDER',folder);continue
        state={};saved=defaultdict(set);non=defaultdict(set)
        for p in sorted(folder.glob('*.json')):
            if not DATE_RE.fullmatch(p.name):continue
            try:d=json.loads(p.read_text(encoding='utf-8'))
            except Exception as e:
                days.append(dict(year=y,date=p.stem,status='corrupt',articles=0,non_articles=0,failures=0,error=str(e)))
                continue
            date=d.get('date') or p.stem
            state[date]=d
            for a in d.get('articles',[]):
                u=canon(a.get('url'))
                if u:saved[date].add(u)
            for a in d.get('non_articles',[]):
                u=canon(a.get('url'))
                if u:non[date].add(u)
            days.append(dict(year=y,date=date,status=d.get('status'),articles=len(d.get('articles',[])),non_articles=len(d.get('non_articles',[])),failures=d.get('failed_count',0),error=''))
        historical={}; log=folder/'failed_urls.jsonl';bad=0
        if log.exists():
            with log.open(encoding='utf-8') as f:
                for line in f:
                    if not line.strip():continue
                    try:r=json.loads(line)
                    except Exception:bad+=1;continue
                    date=r.get('date');u=canon(r.get('url'))
                    if not date or not u or '/nw.' not in urlsplit(u).path:continue
                    historical[(date,u)]=r
        for (date,u),r in historical.items():
            d=state.get(date,{})
            resolved='success' if u in saved[date] else ('non_article' if u in non[date] else 'unmatched')
            rows.append(dict(year=y,date=date,url=u,match_status=resolved,day_status=d.get('status','missing'),current_day_failed_count=d.get('failed_count',''),last_logged_error=cat(r.get('error')),last_logged_error_detail=str(r.get('error',''))[:300],source='historical_failure_log'))
        n=Counter(r['match_status'] for r in rows if r['year']==y)
        print(f'{y}: state_days={len(state)} historical_unique_urls={sum(n.values())} matched_success={n["success"]} matched_non_article={n["non_article"]} unmatched={n["unmatched"]}; bad_log_lines={bad}')
    with (out/'historical_url_reconciliation.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['year','date','url','match_status','day_status','current_day_failed_count','last_logged_error','last_logged_error_detail','source']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    with (out/'daily_latest_status.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['year','date','status','articles','non_articles','failures','error'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(days)
    # A conservative candidate subset: unresolved historical failed article URLs on non-complete days.
    candidates=[r for r in rows if r['match_status']=='unmatched' and r['day_status'] in ('partial','failed')]
    with (out/'candidate_urls_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['year','date','url','match_status','day_status','current_day_failed_count','last_logged_error','last_logged_error_detail','source'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(candidates)
    summary={'state_days':len(days),'historical_url_records':len(rows),'matches':dict(Counter(r['match_status'] for r in rows)),'candidate_urls_for_review':len(candidates),'candidate_error_types':dict(Counter(r['last_logged_error'] for r in candidates)),'note':'Candidates are from historical logs, NOT verified current missing URLs; state lacks a guaranteed current discovered_urls inventory. Do not auto-download all.'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Output:',out.resolve());print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
