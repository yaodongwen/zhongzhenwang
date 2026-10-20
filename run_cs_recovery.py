#!/usr/bin/env python3
"""One-command conservative recovery using existing audit_unresolved.py & repair_urls.py.
Does not crawl unseen article URLs. Never runs concurrently with other CS writers.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description='Audit historical errors and retry selected article URLs; no full-year recrawl.')
    ap.add_argument('--years', type=int, nargs='+', required=True)
    ap.add_argument('--state-root', default='data/raw/cs/state_by_year')
    ap.add_argument('--output-dir', default='data/raw/cs')
    ap.add_argument('--qc-dir', default='data/qc/cs_recovery')
    ap.add_argument('--delay', type=float, default=2.0)
    ap.add_argument('--limit-urls', type=int, default=100, help='0 = unlimited (only after checking sample)')
    ap.add_argument('--types', nargs='+', default=['legacy_title','http_5xx','ssl','timeout','connection','rate_limit'])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--audit-only', action='store_true')
    args = ap.parse_args()
    root = Path(args.state_root)
    required = ('audit_unresolved.py', 'repair_urls.py', 'cs_epaper.py')
    for filename in required:
        if not Path(filename).is_file():
            ap.error(f'Missing {filename}; run from project directory after copying audit/repair scripts')
    for yr in args.years:
        folder = root / str(yr)
        if not folder.is_dir():
            ap.error(f'Missing state folder: {folder} (do not repair from unrelated annual JSONL)')
        if not list(folder.glob(f'{yr}-??-??.json')):
            ap.error(f'No daily state files in {folder}')
    if not (0 <= args.limit_urls <= 1000000):
        ap.error('--limit-urls must be >=0')
    years = [str(x) for x in sorted(set(args.years))]
    out = Path(args.qc_dir)
    out.mkdir(parents=True, exist_ok=True)
    audit = [sys.executable, 'audit_unresolved.py', '--state-root', str(root), '--years', *years, '--out-dir', str(out)]
    print('AUDIT:', ' '.join(audit), flush=True)
    subprocess.run(audit, check=True)
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    print('Candidates:',summary['candidate_urls_for_review'], 'by type:',summary.get('candidate_error_types'),flush=True)
    if args.audit_only:
        return
    repair = [sys.executable, 'repair_urls.py', '--candidate-csv',str(out/'candidate_urls_review.csv'), '--state-root',str(root), '--output-dir',args.output_dir, '--years',*years, '--types',*args.types, '--limit-urls',str(args.limit_urls),'--delay',str(args.delay)]
    if args.dry_run:
        repair.append('--dry-run')
    print('REPAIR:', ' '.join(repair), flush=True)
    subprocess.run(repair, check=True)
    print('Done. QC flags and original date statuses remain subject to revalidation.',flush=True)

if __name__=='__main__':
    main()
