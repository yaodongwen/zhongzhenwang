#!/usr/bin/env python3
"""Conservative CS epaper article URL repair: no listing requests, no invented completion."""
import argparse,csv,datetime as dt,json,logging,re,sys,time
from collections import defaultdict,Counter
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

from cs_epaper import Client,parse_article,canonical,write_json,rebuild_year_jsonl

LOG=logging.getLogger('cs_url_repair')
DATE_PATH=re.compile(r'/zgzqb/html/(\d{4})-(\d{2})/(\d{2})/(?:nw\.|content_)',re.I)
EDITION=re.compile(r'-([A-Z]\d{2,3})\.html?$',re.I)

def normalize(u):
    p=urlsplit(u or '')
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,'',''))

def read_candidates(path, years, selected_types):
    output=defaultdict(list); seen=set()
    with path.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            try: year=int(row['year'])
            except (ValueError,KeyError):continue
            if year not in years or (selected_types and row.get('last_logged_error') not in selected_types):continue
            u=normalize(row.get('url',''))
            p=urlsplit(u); m=DATE_PATH.search(p.path)
            if p.scheme!='https' or p.hostname!='epaper.cs.com.cn' or not m: continue
            date=f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
            if date != row.get('date') or int(m.group(1))!=year: continue
            ed=EDITION.search(p.path)
            if not ed: continue
            key=(date,u)
            if key in seen:continue
            seen.add(key)
            output[(year,date)].append((u,ed.group(1).upper(),row.get('last_logged_error','')))
    return output

def merge_day(day, candidates, client, dry_run, log_file, max_urls, on_attempt=None):
    saved={normalize(a.get('url')):a for a in day.get('articles',[]) if isinstance(a,dict) and a.get('url')}
    non={normalize(a.get('url')):a for a in day.get('non_articles',[]) if isinstance(a,dict) and a.get('url')}
    results=Counter(); latest_errors=[]
    for url,edition,category in candidates:
        if url in saved or url in non:
            results['already_saved']+=1;continue
        if max_urls is not None and results['attempted']>=max_urls:
            results['deferred']+=1;continue
        if dry_run:
            results['would_fetch']+=1;continue
        results['attempted']+=1
        try:
            html,final=client.get(url)
            # Reject redirects across URLs or dates: never attach wrong article.
            if normalize(final)!=url:raise ValueError('redirected to unexpected URL: '+final)
            article=parse_article(html,final,day['date'],edition,'')
            if article.get('_non_article'):
                non[url]=article;results['non_article']+=1
            else:
                saved[url]=article;results['recovered']+=1
        except Exception as e:
            err={'date':day['date'],'url':url,'edition':edition,'error':str(e)[:300],'stage':'url_repair','error_category':category,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}
            latest_errors.append(err);results['still_failed']+=1
            with log_file.open('a',encoding='utf-8') as f:f.write(json.dumps(err,ensure_ascii=False)+'\n')
        finally:
            if on_attempt is not None:
                on_attempt(results)
    if not dry_run and results['attempted']:
        # Preserve original daily status and failure metadata: recovery alone
        # cannot attest complete enumeration of an edition.
        day['articles']=list(saved.values());day['non_articles']=list(non.values())
        day['article_count']=len(saved);day['non_article_count']=len(non)
        day['recovery_last_attempted']=results['attempted']
        day['recovery_last_recovered']=results['recovered']
        day['recovery_last_failed']=results['still_failed']
        day['recovery_checked_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        day['recovery_note']='Original status and failed_count preserved pending listing verification; partial/failed may contain valid saved articles.'
        day['recovery_unresolved_samples']=latest_errors[:20]
    return results

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--candidate-csv',default='data/qc/cs_recovery/candidate_urls_review.csv')
    p.add_argument('--state-root',default='data/raw/cs/state_by_year')
    p.add_argument('--output-dir',default='data/raw/cs')
    p.add_argument('--years',type=int,nargs='+',default=[2016,2017])
    p.add_argument('--types',nargs='*',default=['legacy_title','http_5xx'])
    p.add_argument('--delay',type=float,default=2.0)
    p.add_argument('--timeout',type=float,default=25)
    p.add_argument('--retries',type=int,default=2)
    p.add_argument('--limit-urls',type=int,default=30,help='Max HTTP attempts overall; 0 means unlimited')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--progress-every',type=int,default=1,help='Print URL attempt progress every N requests')
    args=p.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    groups=read_candidates(Path(args.candidate_csv),set(args.years),set(args.types))
    client=Client(args.delay,args.timeout,args.retries)
    total=Counter(); touched=set(); remaining=None if args.limit_urls==0 else args.limit_urls
    root=Path(args.state_root)
    # The denominator counts only URLs not already present in current checkpoints,
    # not historical failures, dates with a state record, or deferred entries.
    pending=0
    for (yr,day_date),urls in sorted(groups.items()):
        state_path=root/str(yr)/(day_date+'.json')
        if not state_path.exists():continue
        try:
            state=json.loads(state_path.read_text(encoding='utf-8'))
            known={normalize(a.get('url')) for field in ('articles','non_articles')
                   for a in (state.get(field) or []) if isinstance(a,dict)}
            pending+=sum(1 for u,_,_ in urls if u not in known)
        except (OSError,ValueError,TypeError):pass
    target=min(pending,args.limit_urls) if args.limit_urls else pending
    started=time.monotonic()
    print(f'REPAIR PLAN: remaining_candidates={pending:,} this_run_target={target:,} (not verified missing news)',flush=True)
    progress_count=0
    def on_attempt(day_counts):
        nonlocal progress_count
        progress_count+=1
        if progress_count % max(1,args.progress_every) and progress_count!=target:return
        # Global counts include all completed days; day_counts covers current date.
        recovered=total['recovered']+day_counts['recovered']
        non_articles=total['non_article']+day_counts['non_article']
        failures=total['still_failed']+day_counts['still_failed']
        ratio=(progress_count/target*100) if target else 100
        width=22;filled=round(width*progress_count/target) if target else width
        elapsed=max(time.monotonic()-started,0.01)
        speed=progress_count/elapsed
        eta=(target-progress_count)/speed if speed else 0
        print(f'PROGRESS [{"█"*filled}{"░"*(width-filled)}] {progress_count:,}/{target:,} ({ratio:5.1f}%) '
              f'recovered={recovered:,} non_article={non_articles:,} failed={failures:,} '
              f'rate={speed:.2f}/s ETA={eta/60:.1f}min',flush=True)
    for (year,date),urls in sorted(groups.items()):
        path=root/str(year)/(date+'.json')
        if not path.exists():
            LOG.warning('NO STATE %s',path);total['missing_state']+=len(urls);continue
        day=json.loads(path.read_text(encoding='utf-8'))
        if day.get('date')!=date: raise ValueError('state date mismatch '+str(path))
        folder=root/str(year)
        log=folder/'url_repair_failures.jsonl'
        stats=merge_day(day,urls,client,args.dry_run,log,remaining,None if args.dry_run else on_attempt)
        total.update(stats)
        if not args.dry_run and stats['attempted']:
            write_json(path,day)
            rebuild_year_jsonl(folder,Path(args.output_dir)/f'cs_epaper_{year}.jsonl')
            touched.add(year)
        if remaining is not None:
            remaining-=stats['attempted']
        if stats['attempted'] or stats['would_fetch'] or stats['already_saved']:
            LOG.info('%s candidates=%d recovered=%d failed=%d already=%d dryrun=%d',date,len(urls),stats['recovered'],stats['still_failed'],stats['already_saved'],stats['would_fetch'])
        if remaining is not None and remaining<=0:break
    print(json.dumps({'stats':dict(total),'years_updated':sorted(touched),'dry_run':args.dry_run},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
