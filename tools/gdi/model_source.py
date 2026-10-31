"""Pressure-level adapters using each provider's own inventory and byte offsets."""
from sources import HRRRSource
from eccodes import codes_new_from_message,codes_get,codes_release,codes_get_message,codes_grib_new_from_file,codes_grib_multi_support_on,codes_grib_multi_support_reset_file
import pathlib,tempfile
LEVELS=(950,850,700,500)
ROOTS={
 'hrrr':{'aws':'https://noaa-hrrr-bdp-pds.s3.amazonaws.com','nomads':'https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod'},
 'rap':{'aws':'https://noaa-rap-pds.s3.amazonaws.com','nomads':'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rap/prod'},
 'rrfs':{'aws':'https://noaa-rrfs-ops-pds.s3.amazonaws.com','nomads':'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod'}}

def record_handle(raw,record):
 """Select the indexed GRIB subfield; RAP packs U and V in one message."""
 if 'submessage' not in record:return codes_new_from_message(raw)
 submessage=record['submessage']
 if not isinstance(submessage,int) or not 1<=submessage<=8:raise ValueError('Invalid GRIB submessage')
 codes_grib_multi_support_on()
 with tempfile.TemporaryFile() as f:
  f.write(raw);f.seek(0)
  selected=None
  try:
   i=0
   while True:
    h=codes_grib_new_from_file(f)
    if h is None:break
    i+=1
    try:
     if i==submessage:selected=codes_get_message(h)
    finally:codes_release(h)
  finally:codes_grib_multi_support_reset_file(f)
 if selected is None:raise ValueError('Missing indexed GRIB submessage')
 # No live handle may depend on a multi-field reader/file context being reset.
 return codes_new_from_message(selected)
class PressureSource(HRRRSource):
 def __init__(self,model,cycle,cache='run/gdi-cache',**kwargs):
  super().__init__(cycle,pathlib.Path(cache)/model,product='prs',**kwargs);self.model=model
 def url(self,provider,lead):
  c=self.cycle
  if self.model=='hrrr':suffix=f'/hrrr.{c:%Y%m%d}/conus/hrrr.t{c:%H}z.wrfprsf{lead:02d}.grib2'
  elif self.model=='rap':suffix=f'/rap.{c:%Y%m%d}/rap.t{c:%H}z.awp130pgrbf{lead:02d}.grib2'
  else:suffix=f'/rrfs.{c:%Y%m%d}/{c:%H}/rrfs.t{c:%H}z.prslev.3km.f{lead:03d}.conus.grib2'
  return ROOTS[self.model][provider]+suffix
 def inventory(self,provider,lead,refresh=False):
  key=(provider,lead)
  with self.lock:
   if key in self.indices and not refresh:return self.indices[key]
  u=self.url(provider,lead)
  try:raw_index=self.transport(u+'.idx')
  except Exception:
   if self.model!='rrfs' or provider!='nomads':raise
   u=u.replace('/rrfs/prod/','/rrfs/para/');raw_index=self.transport(u+'.idx')
  lines=raw_index.decode().strip().splitlines();records={}
  parsed=[line.split(':') for line in lines]
  offsets=list(dict.fromkeys(int(x[1]) for x in parsed))
  if offsets!=sorted(offsets):raise ValueError('Unordered physical GRIB messages')
  ends={start:end-1 for start,end in zip(offsets,offsets[1:])}
  for x in parsed:
   if x[3] not in ('TMP','SPFH','RH','PRES','UGRD','VGRD','PWAT'):continue
   k=(x[3],x[4]);start=int(x[1])
   if start not in ends:continue
   end=ends[start]
   if x[2]!=f'd={self.cycle:%Y%m%d%H}' or end<start or k in records:raise ValueError('Invalid index')
   records[k]={'variable':k[0],'level':k[1],'start':start,'end':end,'url':u,'provider':provider,'forecast_hour':lead}
   if '.' in x[0]:records[k]['submessage']=int(x[0].split('.')[1])
  if self.model=='rrfs':
   surface_url=u.replace('.prslev.','.2dfld.');surface_lines=self.transport(surface_url+'.idx').decode().strip().splitlines()
   parsed_surface=[line.split(':') for line in surface_lines]
   surface_offsets=list(dict.fromkeys(int(x[1]) for x in parsed_surface))
   if surface_offsets!=sorted(surface_offsets):raise ValueError('Unordered RRFS surface messages')
   surface_ends={a:b-1 for a,b in zip(surface_offsets,surface_offsets[1:])}
   for x in parsed_surface:
    # The pressure file's PWAT is a shallow above-ground layer. Only the
    # separate 2-D file contains the total atmospheric column required here.
    if x[3:5]!=['PRES','surface'] and not (x[3]=='PWAT' and x[4].startswith('entire atmosphere')):continue
    start=int(x[1])
    if start not in surface_ends:continue
    if x[2]!=f'd={self.cycle:%Y%m%d%H}':raise ValueError('Invalid RRFS surface index')
    key=(x[3],x[4])
    records[key]={'variable':key[0],'level':key[1],'start':start,'end':surface_ends[start],'url':surface_url,'provider':provider,'forecast_hour':lead}
    if '.' in x[0]:records[key]['submessage']=int(x[0].split('.')[1])
  required=[('TMP',f'{p} mb') for p in LEVELS]+[('PRES','surface')]
  if any(k not in records for k in required) or any(not any((v,f'{p} mb') in records for v in ('SPFH','RH')) for p in LEVELS):raise ValueError('Missing GDI inputs')
  with self.lock:self.indices[key]=records
  return records
 def _validate(self,b,rec):
  if b[:4]!=b'GRIB' or b[-4:]!=b'7777' or int.from_bytes(b[8:16],'big')!=len(b):raise ValueError('Truncated GRIB')
  h=record_handle(b,rec)
  try:
   if (codes_get(h,'dataDate'),codes_get(h,'dataTime'),codes_get(h,'endStep'))!=(int(self.cycle.strftime('%Y%m%d')),self.cycle.hour*100,rec['forecast_hour']):raise ValueError('Cycle/lead mismatch')
   expected=('lambert',451,337) if self.model=='rap' else ('lambert',1799,1059)
   if (codes_get(h,'gridType'),codes_get(h,'Nx'),codes_get(h,'Ny'))!=expected:raise ValueError('Unexpected model grid')
   v=rec['variable'];name=codes_get(h,'shortName');units=codes_get(h,'units')
   if name not in {'TMP':('t',),'SPFH':('q',),'RH':('r',),'PRES':('pres','sp'),'UGRD':('u',),'VGRD':('v',),'PWAT':('pwat','tcwv')}[v] or units not in {'TMP':('K',),'SPFH':('kg kg**-1','kg kg-1'),'RH':('%',),'PRES':('Pa',),'UGRD':('m s**-1','m s-1'),'VGRD':('m s**-1','m s-1'),'PWAT':('kg m**-2','kg m-2')}[v]:raise ValueError('Variable/unit mismatch')
   level=rec['level'];typ=codes_get(h,'typeOfLevel')
   if level=='surface':
    if typ!='surface':raise ValueError('Expected surface')
   elif v=='PWAT':
    if not level.startswith('entire atmosphere') or typ not in ('atmosphere','entireAtmosphere','atmosphereSingleLayer'):raise ValueError('Expected total-column water')
   elif typ!='isobaricInhPa' or codes_get(h,'level')!=int(level.split()[0]):raise ValueError('Pressure level mismatch')
   sig=codes_get(h,'md5Section3')
   if self.grid is not None and self.grid!=sig:raise ValueError('Mixed grids')
   self.grid=sig;return sig
  finally:codes_release(h)
 def acquire(self,provider,lead,variable,level):
  # Providers may publish q or RH differently. Select from this provider's
  # own inventory; decode_model uses the returned variable and converts RH.
  if variable in ('SPFH','RH'):
   inv=self.inventory(provider,lead)
   if (variable,level) not in inv:
    alternate='RH' if variable=='SPFH' else 'SPFH'
    if (alternate,level) not in inv:raise ValueError('Missing humidity input')
    variable=alternate
  return super().acquire(provider,lead,variable,level)
 def tasks(self,lead):
  failures=[]
  for provider in self.providers:
   try:
    inv=self.inventory(provider,lead)
    return [(lead,'TMP',f'{p} mb') for p in LEVELS]+[(lead,'SPFH' if ('SPFH',f'{p} mb') in inv else 'RH',f'{p} mb') for p in LEVELS]+[(lead,'PRES','surface')]
   except Exception as e:failures.append({'provider':provider,'error':str(e)})
  raise ValueError('No complete inventory: '+str(failures))
