#!/usr/bin/env python3
"""Read-only inventory of Git data, live Pages payload, caches and artifacts.

These are distinct storage pools. Public API totals cannot verify the owner's
billing balance, plan, spending budget, private repositories or bandwidth use.
"""
import argparse
import base64
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import urllib.request


def audit(repository, output=None):
    base = 'https://api.github.com/repos/'+repository
    def get(path):
        headers={'Accept':'application/vnd.github+json','User-Agent':'WPC-Storage-Audit/1'}
        if os.environ.get('GITHUB_TOKEN'):
            headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
        request = urllib.request.Request(base+path, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    repo = get('')
    head = get('/git/ref/heads/pages-live')['object']['sha']
    commit = get('/git/commits/'+head)
    tree = get('/git/trees/'+commit['tree']['sha']+'?recursive=1')
    caches = get('/actions/caches?per_page=100')
    first = get('/actions/artifacts?per_page=100&page=1')
    pages = math.ceil(first['total_count']/100)
    if pages > 60: raise ValueError('Artifact inventory exceeds bounded 6,000-row audit')
    artifacts = {a['id']:a for a in first['artifacts']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda page:get('/actions/artifacts?per_page=100&page='+str(page)),range(2,pages+1)):
            artifacts.update({a['id']:a for a in result['artifacts']})
    grouped = defaultdict(lambda:{'count':0,'bytes':0})
    for row in artifacts.values():
        if row.get('expired'): continue
        name = re.sub(r'\d{8,}', '*', row['name'])
        grouped[name]['count'] += 1
        grouped[name]['bytes'] += row['size_in_bytes']
    cache_rows = caches.get('actions_caches',[])
    branches = get('/branches?per_page=100')
    runtime = [b for b in branches if b['name'].startswith('data/')
               or b['name'] in ('mrms-rala-data','surface-data','wfigs-data')]
    def snapshot(branch):
        sha=branch['commit']['sha']; commit=get('/git/commits/'+sha)
        tree=get('/git/trees/'+commit['tree']['sha']+'?recursive=1')
        row={'branch':branch['name'],'head':sha,'parent_count':len(commit.get('parents',[])),
             'tree_complete':not tree.get('truncated'),
             'payload_bytes':sum(p.get('size',0) for p in tree['tree'] if p['type']=='blob'),
             'blob_count':sum(p['type']=='blob' for p in tree['tree'])}
        if branch['name']=='mrms-rala-data':
            content=get('/contents/mrms_rala_loop_manifest.json?ref='+sha)
            manifest=json.loads(base64.b64decode(content['content']))
            row['radar_archive']={'frame_count':manifest['frame_count'],
                'first_valid_utc':manifest['frames'][0]['valid_time_utc'],
                'last_valid_utc':manifest['latest_valid_time_utc'],
                'generated_utc':manifest['generated_utc'],
                'publication_validation':manifest.get('publication_validation')}
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots=list(pool.map(snapshot,runtime))
    report = {
        'observed_at_utc':datetime.now(timezone.utc).isoformat(), 'repository':repository,
        'repository_reported_kib':repo['size'], 'repository_reported_gib':repo['size']/1024**2,
        'pages_head':head, 'pages_tree_sha':tree['sha'],
        'pages_parent_count':len(commit.get('parents',[])),
        'pages_tree_complete':not tree.get('truncated'),
        'pages_payload_bytes':sum(p.get('size',0) for p in tree['tree'] if p['type']=='blob'),
        'runtime_branch_inventory_complete':len(branches)<100,
        'runtime_snapshots':snapshots,
        'cache_count':caches['total_count'], 'cache_inventory_complete':caches['total_count'] <= 100,
        'cache_bytes':sum(r['size_in_bytes'] for r in cache_rows),
        'largest_caches':sorted([{'key':r['key'],'bytes':r['size_in_bytes']} for r in cache_rows],key=lambda r:r['bytes'],reverse=True)[:10],
        'artifact_reported_count_at_start':first['total_count'], 'artifact_distinct_rows_observed':len(artifacts),
        'artifact_live_bytes_observed':sum(v['bytes'] for v in grouped.values()),
        'artifact_groups':dict(sorted(grouped.items(),key=lambda item:item[1]['bytes'],reverse=True)),
        'limits':{'pages_hard_bytes':1024**3,'local_pages_safety_budget_bytes':512*1024**2,
                  'new_flash_flood_suite_budget_bytes_each':32*1024**2},
        'qualification':'Read-only observation across a changing repository; pagination may overlap while jobs finish. No billing or bandwidth guarantee. GitHub controls garbage collection of unreachable Git objects.',
    }
    if output:
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',default='andreworrison-cloud/wpc-hydro-dashboard')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit(args.repository,args.output),indent=2))
