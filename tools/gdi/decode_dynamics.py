"""Validated AWS/NOMADS inputs for RAP, HRRR and RRFS companion diagnostics."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import numpy as np
from eccodes import codes_new_from_message, codes_get, codes_get_array, codes_release
from model_source import PressureSource, record_handle
from dynamics import RECIPE, SIGMA_KM, Geometry, calculate, MFC_LEVELS, UPPER_LEVELS, LOWER_LEVELS


def tasks(source, lead):
    failures = []
    for provider in source.providers:
        try:
            inv = source.inventory(provider, lead)
            requested = [('PRES','surface')]
            for p in sorted(set(MFC_LEVELS+UPPER_LEVELS+LOWER_LEVELS), reverse=True):
                requested += [(v,f'{p} mb') for v in ('UGRD','VGRD')]
            for p in MFC_LEVELS:
                level = f'{p} mb'
                requested += [('TMP',level),('SPFH' if ('SPFH',level) in inv else 'RH',level)]
            for p in (400,300):
                level = f'{p} mb'
                requested += [('TMP',level),('RH' if ('RH',level) in inv else 'SPFH',level)]
            column = [k for k in inv if k[0] == 'PWAT' and k[1].startswith('entire atmosphere')]
            if len(column) != 1 or any(k not in inv for k in requested):
                raise ValueError('Missing diagnostic inventory records')
            return [(lead,*k) for k in dict.fromkeys(requested+column)]
        except Exception as e:
            failures.append({'provider':provider,'error':str(e)})
    raise ValueError('No complete dynamics inventory: '+str(failures))


def decode(cycle, lead, out, cache, model='rap'):
    if model not in ('rap','hrrr','rrfs') or not 0 <= lead <= 84:
        raise ValueError('Invalid model/forecast hour')
    source = PressureSource(model,cycle,cache=cache)
    fields, provenance, flags = {}, [], None
    lat = lon = spacing = radius = projection = None
    for meta, raw in source.fetch_batch(tasks(source,lead)):
        h = record_handle(raw,meta)
        try:
            shape = (codes_get(h,'Ny'),codes_get(h,'Nx'))
            a = codes_get_array(h,'values').reshape(shape)
            a = np.where(a == codes_get(h,'missingValue'), np.nan, a)
            if meta['variable'] == 'PWAT':
                fields['PWAT','column'] = a
            else:
                fields[meta['variable'],meta['level']] = a
            if lat is None:
                lat = codes_get_array(h,'latitudes').reshape(shape)
                lon = (codes_get_array(h,'longitudes').reshape(shape)+180)%360-180
                spacing = (float(codes_get(h,'DxInMetres')),float(codes_get(h,'DyInMetres')))
                radius = float(codes_get(h,'radiusInMetres'))
                low,high = (12000,15000) if model == 'rap' else (2900,3100)
                if not low < min(spacing) <= max(spacing) < high or not 6.3e6 < radius < 6.5e6:
                    raise ValueError('Unexpected native spacing or earth radius')
                projection = {'lat_1':float(codes_get(h,'Latin1InDegrees')),
                              'lat_2':float(codes_get(h,'Latin2InDegrees')),
                              'lat_0':float(codes_get(h,'LaDInDegrees')),
                              'lon_0':float(codes_get(h,'LoVInDegrees')),'radius':radius}
            if meta['variable'] in ('UGRD','VGRD'):
                f = {'grid_relative':bool(codes_get(h,'uvRelativeToGrid')),
                     'i_negative':bool(codes_get(h,'iScansNegatively')),
                     'j_positive':bool(codes_get(h,'jScansPositively'))}
                if flags is not None and flags != f:
                    raise ValueError('Mixed wind orientation flags')
                flags = f
        finally:
            codes_release(h)
        provenance.append(meta)
        print(model.upper(),'dynamics',cycle,lead,meta['variable'],meta['level'],meta['provider'],flush=True)
    result = calculate(fields,Geometry(lon,lat,radius),dx=spacing[0],dy=spacing[1],wind_flags=flags)
    inside = (lon >= -125)&(lon <= -66)&(lat >= 24)&(lat <= 50)
    result = {k:np.where(inside,a,np.nan).astype('float32') for k,a in result.items()}
    if any(np.isfinite(result[k]).sum() < 1000 for k in ('mfc','div','rh','pw')):
        raise ValueError('Insufficient valid dynamics coverage')
    out = Path(out)
    out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out,latitude=lat,longitude=lon,**result)
    stamp = {'model':model,'recipe':RECIPE if model=='rap' else 'cam_gdi_dynamics_v1','cycle':dt.datetime.strptime(cycle,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc).isoformat(),
             'lead':lead,'grid_md5':source.grid,'wind_flags':flags,'dx_m':spacing[0],'dy_m':spacing[1],'radius_m':radius,
             'projection':projection,'smoothing_sigma_km':SIGMA_KM,'sources':provenance,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
             'humidity_conversion':'RH to q using Bolton liquid-water saturation; mixing ratio r=q/(1-q) for moisture flux',
             'moisture_convergence':'Pressure mean of levelwise -div(r*wind), complete above-ground segments 950/900/850/700 hPa, minimum 100 hPa depth',
             'derivatives':'Earth-relative winds; actual native lat/lon Jacobian and spherical metric',
             'filter':'Gaussian sigma 20 km in native projected coordinates; 80% finite support and valid center',
             'ranges':{k:{'min':float(np.nanmin(a)),'max':float(np.nanmax(a)),'finite_cells':int(np.isfinite(a).sum())} for k,a in result.items()}}
    out.with_suffix('.json').write_text(json.dumps(stamp,indent=2))
    return stamp


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--model',choices=('rap','hrrr','rrfs'),default='rap')
    p.add_argument('--cycle',required=True)
    p.add_argument('--lead',type=int,required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--cache',default='run/rap-dynamics/cache')
    a = p.parse_args()
    decode(a.cycle,a.lead,a.out,a.cache,a.model)
