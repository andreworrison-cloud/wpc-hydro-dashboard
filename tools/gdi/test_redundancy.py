"""Fault injection for provider fallback; no meteorological equations are mocked."""
import tempfile
from model_source import PressureSource

def exercise(model, failure, order=('aws','nomads'), dynamics=False):
    requests=[]
    primary,backup=order
    def provider(url):return 'aws' if 'amazonaws.com' in url else 'nomads'
    def transport(url,start=None,end=None):
        p=provider(url);requests.append((p,url,start,end))
        if p==primary and failure=='index':raise OSError('inventory unavailable')
        if start is None:
            # Different offsets and moisture representations on each provider.
            variables=[(v,f'{lev} mb') for v in ('TMP','SPFH' if p==primary else 'RH') for lev in (950,850,700,500)]
            if dynamics:
                variables += [(v,f'{lev} mb') for v in ('TMP','SPFH' if p==primary else 'RH') for lev in (1000,900,400,300,200)]
                variables += [(v,f'{lev} mb') for v in ('UGRD','VGRD') for lev in (1000,950,900,850,700,400,300,200)]
                column='30-0 mb above ground' if model=='rrfs' and '.2dfld.' not in url else 'entire atmosphere (considered as a single layer)'
                variables += [('PWAT',column)]
            if model!='rrfs' or '.2dfld.' in url:variables+=[('PRES','surface')]
            variables+=[('END','surface')]
            offset=100 if p==primary else 1000
            return '\n'.join(f'{i+1}:{offset+i*10}:d=2026101912:{v}:{level}:3 hour fcst:' for i,(v,level) in enumerate(variables)).encode()
        if p==primary and failure=='range':raise OSError('range request failed')
        return b'bad' if p==primary and failure=='decode' else b'valid'
    with tempfile.TemporaryDirectory() as t:
        source=PressureSource(model,'2026101912',cache=t,providers=order,transport=transport)
        def validate(data,record):
            if data!=b'valid':raise ValueError('invalid GRIB')
            return 'grid'
        source.validate=validate
        if dynamics:
            from decode_dynamics import tasks
            requested=tasks(source,3)
        else:requested=source.tasks(3)
        for task in requested:
            meta,_=source.fetch(*task)
            assert meta['provider']==backup
            assert meta['start']>=1000
            if task[1] in ('SPFH','RH'):assert meta['variable']=='RH'
            if model=='rrfs' and task[1]=='PRES':assert '.2dfld.' in meta['url']
            if model=='rrfs' and task[1]=='PWAT':assert '.2dfld.' in meta['url'] and meta['level'].startswith('entire atmosphere')
        assert any(p==backup for p,_,_,_ in requests)

for model in ('hrrr','rap','rrfs'):
    for failure in ('index','range','decode'):
        for order in (('aws','nomads'),('nomads','aws')):exercise(model,failure,order)
for model in ('rap','hrrr','rrfs'):
    for failure in ('index','range','decode'):
        for order in (('aws','nomads'),('nomads','aws')):exercise(model,failure,order,dynamics=True)
print('36 failover cases pass: all GDI models and companion sources, both directions, inventory/range/decoding failures, independent offsets, total-column PWAT and humidity representation')
