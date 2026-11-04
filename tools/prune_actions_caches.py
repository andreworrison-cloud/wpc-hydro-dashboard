"""Retire superseded, rebuildable GDI cache copies in exact main namespaces.

No artifact, branch, publication or scientific archive deletion is supported.
The normal command previews the plan; deletion needs --delete-superseded.
"""
import argparse
from datetime import datetime
import json
import os
import re
import urllib.error
import urllib.request

RETAIN = {'cam-gdi-dynamics-v1-': 1,
          'gdi-focused-forecast-': 2,
          'gdi-focused-day1-': 2}


def plan(rows):
    keep, obsolete = [], []
    for prefix, count in RETAIN.items():
        eligible = [r for r in rows if r.get('ref') == 'refs/heads/main'
                    and re.fullmatch(re.escape(prefix)+r'\d+',r.get('key',''))]
        eligible.sort(key=lambda r:datetime.fromisoformat(r['created_at'].replace('Z','+00:00')),reverse=True)
        keep.extend(eligible[:count]); obsolete.extend(eligible[count:])
    return keep, obsolete


def maintain(repository, token, delete=False):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',repository):
        raise ValueError('Invalid repository identity')
    base=f'https://api.github.com/repos/{repository}/actions/caches'
    def request(url,method='GET'):
        req=urllib.request.Request(url,method=method,headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,'User-Agent':'WPC-Derived-Cache-Maintenance/1','X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                return json.load(response) if method=='GET' else None
        except urllib.error.HTTPError as exc:
            if method=='DELETE' and exc.code==404:return None  # already evicted
            raise
    rows=[]
    for page in range(1,11):
        payload=request(base+f'?per_page=100&page={page}')
        rows.extend(payload['actions_caches'])
        if page*100 >= payload['total_count']:break
    else:raise ValueError('Cache inventory exceeds bounded maintenance request')
    keep,obsolete=plan(rows)
    result={'retained':[{'id':r['id'],'key':r['key'],'bytes':r['size_in_bytes']} for r in keep],
            'superseded':[{'id':r['id'],'key':r['key'],'bytes':r['size_in_bytes']} for r in obsolete],
            'deleted':delete,'bytes_released':sum(r['size_in_bytes'] for r in obsolete) if delete else 0}
    if delete:
        for row in obsolete:
            if not isinstance(row['id'],int):raise ValueError('Invalid cache identifier')
            request(base+'/'+str(row['id']),'DELETE')
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delete-superseded',action='store_true')
    args=parser.parse_args()
    maintain(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_TOKEN'],args.delete_superseded)
