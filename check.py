#!/usr/bin/env python3
import argparse,collections,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('path',nargs='?',default='data/raw/cs/cs_epaper_daily.jsonl');a=p.parse_args()
f=Path(a.path)
if not f.exists():raise SystemExit(f'not found: {f}')
status=collections.Counter();editions=collections.Counter();days=set();article_count=0;dup=0;hashes=set();missing=collections.Counter()
for line in f.open(encoding='utf-8'):
    row=json.loads(line);d=row['date'];status[row['status']]+=1
    if d in days:dup+=1
    days.add(d)
    for x in row.get('articles',[]):
        article_count+=1;editions[x.get('edition_name')]+=1
        if x.get('content_hash') in hashes:dup+=1
        hashes.add(x.get('content_hash'))
        for k in ('title','text','edition','url'):
            if not x.get(k):missing[k]+=1
print('days=',len(days),'articles=',article_count,'duplicates=',dup)
print('status=',dict(status));print('editions=',editions.most_common(15));print('missing=',dict(missing))
