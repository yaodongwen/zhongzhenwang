#!/usr/bin/env python3
"""中国证券报电子报采集: 每个出版日期一条 JSONL, articles 为当天文章数组。"""
import argparse, datetime as dt, hashlib, json, logging, random, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE='https://epaper.cs.com.cn'
HOST='epaper.cs.com.cn'
LOG=logging.getLogger('cs_epaper')
PAGE_RE=re.compile(r'(?:nbs\.|node_).*?\.htm(?:l)?$',re.I)
ARTICLE_RE=re.compile(r'(?:nw\.|content_).*?\.htm(?:l)?$',re.I)
DATE_RE=re.compile(r'/html/(\d{4})[-/](\d{2})/(\d{2})/')
EDITION_RE=re.compile(r'第\s*([A-Z]\d{2,3})\s*版\s*[：:]\s*([^\s|<>]+)')
BAD_EDITION=re.compile(r'信息披露|广告|声明公告|公示|公益广告|证券代码')

def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()

def canonical(url):
    return urldefrag(url)[0].split('?')[0]

def parse_date_in_url(url):
    m=DATE_RE.search(url)
    return dt.date(*map(int,m.groups())).isoformat() if m else None

def dates(start,end):
    d=dt.date.fromisoformat(start); e=dt.date.fromisoformat(end)
    if d>e: raise ValueError('start must not exceed end')
    while d<=e:
        yield d
        d+=dt.timedelta(days=1)

def candidates(d):
    prefix=f'{BASE}/zgzqb/html/{d:%Y-%m}/{d:%d}/'
    # 后期及部分历史月份可能有不同的索引入口，逐一确认页面日期而非盲信 HTTP 200
    return [prefix+'nbs.D110000zgzqb_A01.htm',prefix+'node_2.htm',prefix+'node_tc.htm']

class Client:
    def __init__(self,delay,timeout,retries):
        self.delay=delay; self.timeout=timeout; self.last=0.
        self.s=requests.Session()
        self.s.headers.update({'User-Agent':'Mozilla/5.0 (compatible; ResearchArchive/1.0; personal research)', 'Accept-Language':'zh-CN,zh;q=0.9','Referer':BASE+'/'})
        retry=Retry(total=retries,backoff_factor=1.5,status_forcelist=[429,500,502,503,504],allowed_methods=['GET'],respect_retry_after_header=True)
        self.s.mount('https://',HTTPAdapter(max_retries=retry))
    def get(self,url):
        gap=self.delay-(time.monotonic()-self.last)
        if gap>0: time.sleep(gap)
        self.last=time.monotonic()
        r=self.s.get(url,timeout=self.timeout,allow_redirects=True)
        if r.status_code in (403,429): raise RuntimeError(f'HTTP {r.status_code} access limited: {url}')
        r.raise_for_status()
        if urlparse(r.url).hostname!=HOST: raise ValueError('unexpected redirect host')
        if not r.encoding or r.encoding.lower()=='iso-8859-1': r.encoding=r.apparent_encoding
        return r.text,r.url

def soup_of(html): return BeautifulSoup(html,'html.parser')

def page_links(soup,base):
    result={}
    # Screenshot evidence: a#pageLink in the left page navigation.
    for a in soup.select('a[href]'):
        href=a.get('href',''); url=canonical(urljoin(base,href))
        if urlparse(url).hostname!=HOST or not PAGE_RE.search(urlparse(url).path): continue
        text=clean(a.get_text(' ',strip=True))
        m=EDITION_RE.search(text)
        if not m:
            # Some anchors contain only '第A01版：要闻', others use a#pageLink
            continue
        result[url]={'edition':m.group(1),'edition_name':m.group(2)}
    return result

def article_links(soup,base):
    """Prefer article navigation; if empty, scan entire document.
    Some editions render article navigation in a different subtree.
    """
    edition_match=re.search(r'[_-]([A-Z]\d{2,3})\.html?$', urlparse(base).path,re.I)
    expected_edition=edition_match.group(1).upper() if edition_match else None
    def scan(node):
        result={}
        for a in node.select('a[href]'):
            url=canonical(urljoin(base,a['href'].strip()))
            if urlparse(url).hostname!=HOST: continue
            path=urlparse(url).path
            basename=path.rsplit('/',1)[-1]
            if not (ARTICLE_RE.search(path) or re.match(r'^(?:nw|content)[._-].*?\.html?$', basename,re.I)):
                continue
            if parse_date_in_url(url)!=parse_date_in_url(base):continue
            # IMPORTANT: Historic editions embed whole-newspaper quick navigation.
            # Accept only article URLs ending in the current edition marker.
            if expected_edition:
                am=re.search(r'-([A-Z]\d{2,3})\.html?$',basename,re.I)
                if not am or am.group(1).upper()!=expected_edition:continue
            result[url]=clean(a.get_text(' ',strip=True))
        return result
    primary=soup.select_one('#pagearticles')
    links=scan(primary) if primary else {}
    return links or scan(soup)

def content_lines(node):
    # Preserve paragraph boundaries; <br> inside paragraphs becomes newlines
    clone=BeautifulSoup(str(node),'html.parser')
    for x in clone.select('script,style,iframe,button,form,nav,footer,.advertisement'):
        x.decompose()
    for b in clone.find_all('br'): b.replace_with('\n')
    raw=clone.get_text('\n',strip=True)
    result=[]
    for line in raw.splitlines():
        line=clean(line)
        if line and (not result or line!=result[-1]): result.append(line)
    return result

def parse_article(html,url,issue_date,edition,edition_name):
    soup=soup_of(html)
    if parse_date_in_url(url)!=issue_date:raise ValueError('article URL date mismatch')
    # Modern pages: main/subtitle appear in #div_title.
    # Historical 2016/2017 pages may lack #div_title but preserve a real
    # article <title> (verified on 2016-02-05). Never use article-nav text.
    title_node=soup.select_one('#div_title')
    title_lines=content_lines(title_node) if title_node else []
    if title_lines:
        main_title=title_lines[0]
        subtitle='\n'.join(title_lines[1:]) or None
    else:
        main_title=None
        for sel in ('meta[property="og:title"]', 'meta[name="title"]'):
            node=soup.select_one(sel)
            value=clean(node.get('content','')) if node else ''
            if value and len(value)>=3:
                main_title=value
                break
        if not main_title:
            for sel in ('h1', '#title', '.article-title', '.title'):
                node=soup.select_one(sel)
                value=clean(node.get_text(' ',strip=True)) if node else ''
                if value and len(value)>=3:
                    main_title=value
                    break
        if not main_title and soup.title:
            main_title=clean(soup.title.get_text(' ',strip=True))
        if not main_title or len(main_title)<3 or main_title in ('中国证券报','中国证券报电子报','中证网'):
            raise ValueError('missing article title (#div_title/meta/h1/document.title)')
        subtitle=None  # Do not invent subtitle on legacy templates.
    # 2026-10-16 actual article DOM: div#ozoom > founder-content > p.
    # Older editions may use div#zoom; use explicit fallbacks, not whole-page text.
    body_node=(soup.select_one('#ozoom founder-content')
               or soup.select_one('#ozoom')
               or soup.select_one('#zoom founder-content')
               or soup.select_one('#zoom')
               or soup.select_one('#content founder-content')
               or soup.select_one('#content'))
    if body_node is None:
        ids=[n.get('id') for n in soup.select('[id]') if n.get('id')]
        raise ValueError('body container missing (#ozoom/#zoom); ids=' + ','.join(ids[:30]))
    lines=content_lines(body_node)
    # Many edition items are photo captions or pointers to another edition.
    # A short article must not be discarded solely because it is short.
    text_len=len(''.join(lines))
    if text_len==0:
        # These records are kept in non_articles for audit, not counted as news.
        hint=clean(body_node.get_text(' ',strip=True))
        has_image=bool(body_node.select_one('img') or soup.select_one('#ozoom img,#zoom img'))
        whole=clean(soup.get_text(' ',strip=True))
        pointer=re.search(r'[A-Z]\d{2,3}\s*[·・]\s*[^ ]+',whole)
        kind='edition_pointer' if pointer and not has_image else 'image_only' if has_image else 'empty_body'
        return {'_non_article':True,'kind':kind,'date':issue_date,'edition':edition,
                'edition_name':edition_name,'title':main_title,'subtitle':subtitle,
                'url':url,'body_hint':hint[:150]}

    # Reporter often in leading attribution (●记者某某 / 本报记者某某); do not guess from names elsewhere.
    reporter=None
    for line in lines[:4]:
        m=re.match(r'^[●•\s]*(?:本报|中国证券报)?记者\s*([\u4e00-\u9fa5·、\s]{2,32})$',line)
        if m: reporter=clean(m.group(1));break
    body='\n'.join(lines)
    # Explicit byline may also be printed separately above the body
    if reporter is None:
        for selector in ['#div_author','.author']:
            n=soup.select_one(selector)
            if n:
                t=clean(n.get_text(' ',strip=True))
                m=re.search(r'记者\s*([\u4e00-\u9fa5·、 ]{2,32})',t)
                if m:reporter=clean(m.group(1));break
    digest=hashlib.sha256((main_title+'\n'+body).encode('utf-8')).hexdigest()
    return {'date':issue_date,'source':'cs','source_name':'中国证券报','edition':edition,'edition_name':edition_name,'title':main_title,'subtitle':subtitle,'reporter':reporter,'text':body,'url':url,'content_hash':digest,'text_quality':'short' if text_len<25 else 'normal'}

def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def rebuild_year_jsonl(state, out):
    '''Atomic year snapshot from per-day checkpoints, safe across interruption.'''
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name(out.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        for item in sorted(state.glob('????-??-??.json')):
            obj=json.loads(item.read_text(encoding='utf-8'))
            f.write(json.dumps(obj,ensure_ascii=False)+'\n')
    tmp.replace(out)

def append_failure(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')

def collect(d,client,args,failed,previous=None):
    day=d.isoformat(); index=None; index_url=None; errors=[]
    for candidate in candidates(d):
        try:
            html,final=client.get(candidate)
            soup=soup_of(html)
            if parse_date_in_url(final)!=day: raise ValueError('wrong redirected date')
            if not page_links(soup,final) and not article_links(soup,final):raise ValueError('not an edition index')
            index=soup;index_url=final;break
        except Exception as e:errors.append(f'{candidate}: {str(e)[:160]}')
    if index is None:
        return {'date':day,'source':'cs','source_name':'中国证券报','status':'unavailable','articles':[], 'errors':errors},False
    pages=page_links(index,index_url)
    # Include A01 itself even if its self-link is absent
    pages.setdefault(index_url,{'edition':'A01','edition_name':'要闻'})
    # Incremental repair: keep successful articles and non-article decisions from
    # the previous checkpoint, and fetch only newly discovered/missing URLs.
    # Do not inherit old failure counts: this run revalidates the edition lists.
    previous = previous or {}
    articles = {a['content_hash']: a for a in previous.get('articles', [])
                if isinstance(a, dict) and a.get('content_hash') and a.get('url')}
    non_article_by_url = {canonical(a['url']): a for a in previous.get('non_articles', [])
                          if isinstance(a, dict) and a.get('url')}
    cached_urls = {canonical(a['url']) for a in articles.values()} | set(non_article_by_url)
    failures=0; seen_urls=set(); discovered=0; visited_pages=0; reused=0; fetched=0
    for page_url,meta in pages.items():
        if args.skip_disclosure and BAD_EDITION.search(meta['edition_name']):continue
        try:
            if page_url==index_url:page_soup=index
            else:
                h,final=client.get(page_url)
                if parse_date_in_url(final)!=day:raise ValueError('edition URL date mismatch')
                page_soup=soup_of(h)
            links=article_links(page_soup,page_url)
            visited_pages+=1
            LOG.info('EDITION %s %s discovered_links=%d url=%s',
                     meta['edition'],meta['edition_name'],len(links),page_url)
            if not links:
                # Do not claim successful coverage when a non-disclosure page has no discoverable links.
                if not BAD_EDITION.search(meta['edition_name']):
                    failures+=1
                    append_failure(failed,{'date':day,'stage':'listing_empty','url':page_url,
                                          'error':'No article links found; inspect rendered HTML or selector'})
                continue
            discovered+=len(links)
            for article_url in links:
                if article_url in seen_urls:continue
                seen_urls.add(article_url)
                if args.incremental and canonical(article_url) in cached_urls:
                    reused+=1
                    continue
                try:
                    h,final=client.get(article_url)
                    article=parse_article(h,final,day,meta['edition'],meta['edition_name'])
                    fetched+=1
                    if article.get('_non_article'):
                        non_article_by_url[canonical(article_url)]=article
                        LOG.info('NON_ARTICLE %s %s %s',article['kind'],meta['edition'],article_url)
                    else:
                        articles[article['content_hash']]=article
                except Exception as e:
                    failures+=1;append_failure(failed,{'date':day,'stage':'article','url':article_url,'error':str(e)})
        except Exception as e:
            failures+=1;append_failure(failed,{'date':day,'stage':'edition','url':page_url,'error':str(e)})
    if discovered==0:
        LOG.error('DATE %s: %d editions checked but ZERO article links. '
                  'This indicates a listing parser or site response mismatch.',day,visited_pages)
    # An article can legitimately be on more than one edition, but total URLs
    # must never be attributed to just one edition by whole-paper navigation.
    status='complete' if failures==0 and articles else 'partial' if articles else 'failed'
    obj={'date':day,'source':'cs','source_name':'中国证券报','status':status,'article_count':len(articles),'failed_count':failures,'edition_count':len(pages),'visited_edition_count':visited_pages,'discovered_links':discovered,'non_article_count':len(non_article_by_url),'non_articles':list(non_article_by_url.values()),'articles':list(articles.values()),'reused_articles':reused,'fetched_articles':fetched}
    return obj,status=='complete'

def main():
    ap=argparse.ArgumentParser(description='中国证券报电子报：一天一行JSONL')
    ap.add_argument('--start',required=True);ap.add_argument('--end',required=True)
    ap.add_argument('--output',default='data/raw/cs/cs_epaper_daily.jsonl')
    ap.add_argument('--state-dir',default='data/raw/cs/state')
    ap.add_argument('--delay',type=float,default=2.0);ap.add_argument('--timeout',type=float,default=20)
    ap.add_argument('--retries',type=int,default=2);ap.add_argument('--limit-days',type=int,default=0)
    ap.add_argument('--skip-disclosure',action='store_true',default=True)
    ap.add_argument('--include-disclosure',dest='skip_disclosure',action='store_false')
    ap.add_argument('--retry-failed',action='store_true')
    ap.add_argument('--incremental',action='store_true',help='Reuse saved articles; fetch only missing discovered URLs')
    ap.add_argument('--force-date',action='store_true',help='Rebuild dates even when status=complete (required after parser fixes)')
    args=ap.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    client=Client(args.delay,args.timeout,args.retries)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    state=Path(args.state_dir);state.mkdir(parents=True,exist_ok=True)
    failed=state/'failed_urls.jsonl';processed=0
    for d in dates(args.start,args.end):
        sf=state/(d.isoformat()+'.json')
        if sf.exists():
            old=json.loads(sf.read_text(encoding='utf-8'))
            if not args.force_date and (old.get('status')=='complete' or (not args.retry_failed)):
                LOG.info('SKIP %s %s',d,old.get('status'));continue
        obj,ok=collect(d,client,args,failed,previous=old if args.incremental and sf.exists() and not args.force_date else None)
        write_json(sf,obj)
        rebuild_year_jsonl(state,out)
        LOG.info('DATE %s status=%s articles=%s non_articles=%s failures=%s reused=%s fetched=%s',d,obj['status'],len(obj['articles']),obj.get('non_article_count',0),obj.get('failed_count',0),obj.get('reused_articles',0),obj.get('fetched_articles',0))
        processed+=1
        if args.limit_days and processed>=args.limit_days:break
    # Also rebuild on all-skipped runs. Each completed day already rebuilt atomically.
    rebuild_year_jsonl(state,out)
    LOG.info('OUTPUT %s (days: %d)',out,sum(1 for _ in out.open(encoding='utf-8')))
if __name__=='__main__':main()
