import argparse,collections,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--data-dir',default='data/raw/cs');args=p.parse_args()
for f in sorted(Path(args.data_dir).glob('cs_epaper_20??.jsonl')):
    rows=[json.loads(x) for x in f.open(encoding='utf-8') if x.strip()]
    statuses=collections.Counter(d.get('status') for d in rows)
    articles=sum(len(d.get('articles',[])) for d in rows)
    mismatches=0
    import re
    for d in rows:
        for a in d.get('articles',[]):
            m=re.search(r'-([A-Z]\d{2,3})\.html?$',a.get('url',''),re.I)
            if not m or m.group(1).upper()!=a.get('edition','').upper():mismatches+=1
    print(f'{f.name}: days={len(rows)} articles={articles} statuses={dict(statuses)} wrong_editions={mismatches}')
