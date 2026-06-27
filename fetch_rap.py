import os
import json
import requests
import xarray as xr
import cfgrib
import matplotlib.pyplot as plt
from matplotlib import ticker
import numpy as np
from datetime import datetime, timezone, timedelta
import warnings
import metpy.calc as mpcalc
from metpy.units import units
import scipy.ndimage as ndimage

warnings.filterwarnings('ignore') 

# Ensure the static directory exists for GitHub Pages
os.makedirs("static", exist_ok=True)

print("Connecting to NOAA NOMADS GRIB Filter...")

def download_rap_subset():
    now = datetime.now(timezone.utc)
    
    def fetch_hour(target_time, filename):
        date_str = target_time.strftime('%Y%m%d')
        cycle = f"{target_time.hour:02d}"
        
        url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_rap.pl"
        
        params = {
            'file': f'rap.t{cycle}z.awp130pgrbf00.grib2',
            'lev_surface': 'on', 'lev_2_m_above_ground': 'on', 'lev_10_m_above_ground': 'on',
            'lev_90-0_mb_above_ground': 'on', 'lev_255-0_mb_above_ground': 'on',
            'lev_3000-0_m_above_ground': 'on', 'lev_equilibrium_level': 'on',
            'lev_1000_mb': 'on', 'lev_975_mb': 'on', 'lev_950_mb': 'on',
            'lev_925_mb': 'on', 'lev_900_mb': 'on', 'lev_875_mb': 'on',
            'lev_850_mb': 'on', 'lev_700_mb': 'on', 'lev_500_mb': 'on', 
            'lev_400_mb': 'on', 'lev_300_mb': 'on', 'lev_250_mb': 'on',
            'lev_entire_atmosphere_(considered_as_a_single_layer)': 'on',
            'var_CAPE': 'on', 'var_CIN': 'on', 'var_PWAT': 'on', 'var_UGRD': 'on', 
            'var_VGRD': 'on', 'var_SPFH': 'on', 'var_RH': 'on', 'var_TMP': 'on', 
            'var_HGT': 'on', 'var_HLCY': 'on',
            'dir': f'/rap.{date_str}'
        }
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 200 and len(response.content) > 10000:
            with open(filename, "wb") as f:
                f.write(response.content)
            return target_time
        return None

    # Find the most recent available T-0 Hour
    t0_time = None
    for offset in range(0, 5):
        check_time = now - timedelta(hours=offset)
        t0_time = fetch_hour(check_time, "rap_subset_t0.grib2")
        if t0_time:
            print(f"Success! Downloaded Current RAP (T-0) for: {t0_time.strftime('%Y%m%d %H:00')}Z")
            break
            
    if not t0_time:
        raise Exception("Could not download current RAP data.")

    # Explicitly calculate and fetch the T-3 hour
    t3_target = t0_time - timedelta(hours=3)
    t3_time = fetch_hour(t3_target, "rap_subset_t3.grib2")
    if t3_time:
        print(f"Success! Downloaded Historical RAP (T-3) for: {t3_time.strftime('%Y%m%d %H:00')}Z")
    else:
        print("WARNING: T-3 file not found. 3-Hour change fields will be blank.")

    return t0_time, t3_time

t0_obj, t3_obj = download_rap_subset()
valid_time_str = f"Mesoanalysis F00 &mdash; {t0_obj.strftime('%b %d, %Y %H:00')}Z"

print("Extracting grids and calculating variables...")

def safe_extract(ds, var_name, coord_name, target_val):
    if var_name in ds.data_vars and coord_name in ds.coords:
        c_vals = ds.coords[coord_name].values
        if c_vals.ndim == 0 and c_vals == target_val: return np.squeeze(ds[var_name].values)
        elif c_vals.ndim > 0 and target_val in c_vals: return np.squeeze(ds[var_name].sel({coord_name: target_val}).values)
    return None

# --- PROCESS CURRENT (T-0) FILE ---
datasets_t0 = cfgrib.open_datasets("rap_subset_t0.grib2", indexpath='')

pwat, sbcape, mlcape, mucape, cin = None, None, None, None, None
u_10m, v_10m = None, None
u_925, v_925, t_925 = None, None, None
u_850, v_850, rh_850, t_850 = None, None, None, None
u_700, v_700, rh_700, t_700 = None, None, None, None
u_500, v_500, t_500 = None, None, None
u_400, v_400 = None, None
u_300, v_300 = None, None
u_250, v_250 = None, None
hgt_500, hgt_700, hgt_sfc, t_sfc, hgt_el = None, None, None, None, None
lats, lons = None, None
srh3 = None

u_stack, v_stack, rh_stack, t_stack = [], [], [], []
u_dict, v_dict, z_dict = {}, {}, {}
req_levels = [1000, 975, 950, 925, 900, 875, 850, 700, 500, 400, 300, 250]

for ds in datasets_t0:
    if 'pwat' in ds.data_vars:
        pwat = np.squeeze(ds['pwat'].values)
        lats = ds['latitude'].values
        lons = ds['longitude'].values
        
    if 'cape' in ds.data_vars and 'surface' in ds.coords: sbcape = np.squeeze(ds['cape'].values)
    if 'cin' in ds.data_vars and 'surface' in ds.coords: cin = np.squeeze(ds['cin'].values)
    if 't2m' in ds.data_vars: t_sfc = np.squeeze(ds['t2m'].values)
    if 'orog' in ds.data_vars: hgt_sfc = np.squeeze(ds['orog'].values)
    if 'hlcy' in ds.data_vars: srh3 = np.squeeze(ds['hlcy'].values)
        
    res = safe_extract(ds, 'cape', 'pressureFromGroundLayer', 9000)
    if res is not None: mlcape = res
    res = safe_extract(ds, 'cape', 'pressureFromGroundLayer', 25500)
    if res is not None: mucape = res
    
    for var_name, da in ds.data_vars.items():
        typ = str(da.attrs.get('GRIB_typeOfLevel', '')).lower()
        if da.name in ['gh', 'hgt'] and 'equilibrium' in typ:
            hgt_el = np.squeeze(da.values)
    
    if 'u10' in ds.data_vars: u_10m = np.squeeze(ds['u10'].values)
    if 'v10' in ds.data_vars: v_10m = np.squeeze(ds['v10'].values)
    res_u = safe_extract(ds, 'u', 'heightAboveGround', 10)
    if res_u is not None: u_10m = res_u
    res_v = safe_extract(ds, 'v', 'heightAboveGround', 10)
    if res_v is not None: v_10m = res_v
    
    if 'isobaricInhPa' in ds.coords:
        if 'u' in ds.data_vars:
            u_925 = safe_extract(ds, 'u', 'isobaricInhPa', 925)
            u_850 = safe_extract(ds, 'u', 'isobaricInhPa', 850)
            u_700 = safe_extract(ds, 'u', 'isobaricInhPa', 700)
            u_500 = safe_extract(ds, 'u', 'isobaricInhPa', 500)
            u_400 = safe_extract(ds, 'u', 'isobaricInhPa', 400)
            u_300 = safe_extract(ds, 'u', 'isobaricInhPa', 300)
            u_250 = safe_extract(ds, 'u', 'isobaricInhPa', 250)
        if 'v' in ds.data_vars:
            v_925 = safe_extract(ds, 'v', 'isobaricInhPa', 925)
            v_850 = safe_extract(ds, 'v', 'isobaricInhPa', 850)
            v_700 = safe_extract(ds, 'v', 'isobaricInhPa', 700)
            v_500 = safe_extract(ds, 'v', 'isobaricInhPa', 500)
            v_400 = safe_extract(ds, 'v', 'isobaricInhPa', 400)
            v_300 = safe_extract(ds, 'v', 'isobaricInhPa', 300)
            v_250 = safe_extract(ds, 'v', 'isobaricInhPa', 250)
        if 'r' in ds.data_vars:
            rh_850 = safe_extract(ds, 'r', 'isobaricInhPa', 850)
            rh_700 = safe_extract(ds, 'r', 'isobaricInhPa', 700)
        if 't' in ds.data_vars:
            t_925 = safe_extract(ds, 't', 'isobaricInhPa', 925)
            t_850 = safe_extract(ds, 't', 'isobaricInhPa', 850)
            t_700 = safe_extract(ds, 't', 'isobaricInhPa', 700)
            t_500 = safe_extract(ds, 't', 'isobaricInhPa', 500)
        if 'gh' in ds.data_vars:
            hgt_700 = safe_extract(ds, 'gh', 'isobaricInhPa', 700)
            hgt_500 = safe_extract(ds, 'gh', 'isobaricInhPa', 500)
            
        for lev in req_levels:
            if 'u' in ds.data_vars:
                val = safe_extract(ds, 'u', 'isobaricInhPa', lev)
                if val is not None: u_dict[lev] = val
            if 'v' in ds.data_vars:
                val = safe_extract(ds, 'v', 'isobaricInhPa', lev)
                if val is not None: v_dict[lev] = val
            if 'gh' in ds.data_vars:
                val = safe_extract(ds, 'gh', 'isobaricInhPa', lev)
                if val is not None: z_dict[lev] = val
                
        for level in [1000, 975, 950, 925, 900, 875, 850]:
            if 'u' in ds.data_vars: u_stack.append(safe_extract(ds, 'u', 'isobaricInhPa', level))
            if 'v' in ds.data_vars: v_stack.append(safe_extract(ds, 'v', 'isobaricInhPa', level))
            if 'r' in ds.data_vars: rh_stack.append(safe_extract(ds, 'r', 'isobaricInhPa', level))
            if 't' in ds.data_vars: t_stack.append(safe_extract(ds, 't', 'isobaricInhPa', level))

lons = np.where(lons > 180, lons - 360, lons)
dx, dy = mpcalc.lat_lon_grid_deltas(lons, lats)

if pwat is not None: pwat = pwat / 25.4
if srh3 is None: srh3 = np.zeros_like(lats)
if hgt_sfc is None: hgt_sfc = np.zeros_like(lats)

# --- PROCESS HISTORICAL (T-3) FILE FOR DIFFERENCES ---
pwat_diff, sbcape_diff, mlcape_diff, mucape_diff = None, None, None, None

if t3_obj and os.path.exists("rap_subset_t3.grib2"):
    print("Extracting T-3 variables for difference fields...")
    datasets_t3 = cfgrib.open_datasets("rap_subset_t3.grib2", indexpath='')
    pwat_t3, sbcape_t3, mlcape_t3, mucape_t3 = None, None, None, None
    
    for ds in datasets_t3:
        if 'pwat' in ds.data_vars: pwat_t3 = np.squeeze(ds['pwat'].values) / 25.4
        if 'cape' in ds.data_vars and 'surface' in ds.coords: sbcape_t3 = np.squeeze(ds['cape'].values)
        res = safe_extract(ds, 'cape', 'pressureFromGroundLayer', 9000)
        if res is not None: mlcape_t3 = res
        res = safe_extract(ds, 'cape', 'pressureFromGroundLayer', 25500)
        if res is not None: mucape_t3 = res

    if pwat is not None and pwat_t3 is not None: pwat_diff = pwat - pwat_t3
    if sbcape is not None and sbcape_t3 is not None: sbcape_diff = sbcape - sbcape_t3
    if mlcape is not None and mlcape_t3 is not None: mlcape_diff = mlcape - mlcape_t3
    if mucape is not None and mucape_t3 is not None: mucape_diff = mucape - mucape_t3

print("Executing Deep Kinematic Derivatives...")

def _interp_wind_to_agl(z_agl, w, target_agl):
    z = np.asarray(z_agl, dtype=np.float32)
    w = np.asarray(w, dtype=np.float32)
    target = np.asarray(target_agl, dtype=np.float32)
    target = np.where(np.isfinite(target), target, 6000.0).astype(np.float32)
    finite = np.isfinite(z) & np.isfinite(w)
    below = (z <= target[None, :, :]) & finite
    k = below.sum(axis=0).astype(np.int32) - 1
    k = np.clip(k, 0, z.shape[0] - 2)
    k2 = k + 1
    k3 = k[None, :, :]
    k23 = k2[None, :, :]
    z0 = np.take_along_axis(z, k3, axis=0)[0]
    z1 = np.take_along_axis(z, k23, axis=0)[0]
    w0 = np.take_along_axis(w, k3, axis=0)[0]
    w1 = np.take_along_axis(w, k23, axis=0)[0]
    denom = z1 - z0
    frac = np.where(np.abs(denom) > 1e-3, (target - z0) / denom, 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    out = w0 + frac * (w1 - w0)
    nearest_low = np.take_along_axis(w, k3, axis=0)[0]
    out = np.where(np.isfinite(out), out, nearest_low)
    return out.astype(np.float32)

u_3d = np.stack([u_dict.get(lev, np.zeros_like(lats)) for lev in req_levels])
v_3d = np.stack([v_dict.get(lev, np.zeros_like(lats)) for lev in req_levels])
z_3d = np.stack([z_dict.get(lev, np.zeros_like(lats)) for lev in req_levels])

z_agl = z_3d - hgt_sfc[None, :, :]
if hgt_el is not None:
    el_agl = hgt_el - hgt_sfc
    el_agl = np.where((el_agl >= 2000.0) & (el_agl <= 20000.0), el_agl, 12000.0)
else:
    el_agl = np.full_like(lats, 12000.0)

target_agl = np.clip(0.5 * el_agl, 500.0, 12000.0)
u_top = _interp_wind_to_agl(z_agl, u_3d, target_agl)
v_top = _interp_wind_to_agl(z_agl, v_3d, target_agl)

u_eff = u_top - u_10m
v_eff = v_top - v_10m
spd_eff = np.sqrt(u_eff**2 + v_eff**2) * 1.94384

if cin is not None and sbcape is not None:
    if np.nanpercentile(cin[np.isfinite(cin)], 5) >= 0.0:
        inflow_mask = (sbcape >= 100.0) & (cin <= 250.0)
    else:
        inflow_mask = (sbcape >= 100.0) & (cin >= -250.0)
    spd_eff = np.where(inflow_mask, spd_eff, np.nan)
    u_eff = np.where(inflow_mask, u_eff, np.nan)
    v_eff = np.where(inflow_mask, v_eff, np.nan)

scp = np.zeros_like(lats)
if mucape is not None and spd_eff is not None:
    shear_ms = spd_eff / 1.94384
    shear_term = np.clip(shear_ms / 20.0, 0.0, 1.5)
    shear_term = np.where(shear_ms < 10.0, 0.0, shear_term)
    mucape_safe = np.nan_to_num(mucape, nan=0.0)
    srh_safe = np.nan_to_num(srh3, nan=0.0)
    scp = (mucape_safe / 1000.0) * (srh_safe / 50.0) * shear_term
    scp = np.where(np.isnan(spd_eff), np.nan, scp)

lr_75 = np.zeros_like(lats)
if t_700 is not None and t_500 is not None and hgt_700 is not None and hgt_500 is not None:
    lr_75 = (t_700 - t_500) / (hgt_500 - hgt_700) * 1000 
    
lr_sfc3 = np.zeros_like(lats)
if t_sfc is not None and t_700 is not None and hgt_sfc is not None and hgt_700 is not None:
    dz = np.where((hgt_700 - hgt_sfc) < 500, np.nan, (hgt_700 - hgt_sfc)) 
    lr_sfc3 = (t_sfc - t_700) / dz * 1000

u_mean_83 = np.zeros_like(lats)
v_mean_83 = np.zeros_like(lats)
spd_mean_83 = np.zeros_like(lats)
if all(x is not None for x in [u_850, u_700, u_500, u_400, u_300]):
    u_mean_83 = (75.0*u_850 + 175.0*u_700 + 150.0*u_500 + 100.0*u_400 + 50.0*u_300) / 550.0
    v_mean_83 = (75.0*v_850 + 175.0*v_700 + 150.0*v_500 + 100.0*v_400 + 50.0*v_300) / 550.0
    spd_mean_83 = np.sqrt(u_mean_83**2 + v_mean_83**2) * 1.94384 

u_corfidi_up, v_corfidi_up, spd_corfidi_up = np.zeros_like(lats), np.zeros_like(lats), np.zeros_like(lats)
u_corfidi_down, v_corfidi_down, spd_corfidi_down = np.zeros_like(lats), np.zeros_like(lats), np.zeros_like(lats)
if u_850 is not None and v_850 is not None:
    u_corfidi_up = u_mean_83 - u_850
    v_corfidi_up = v_mean_83 - v_850
    spd_corfidi_up = np.sqrt(u_corfidi_up**2 + v_corfidi_up**2) * 1.94384
    u_corfidi_down = (2.0 * u_mean_83) - u_850
    v_corfidi_down = (2.0 * v_mean_83) - v_850
    spd_corfidi_down = np.sqrt(u_corfidi_down**2 + v_corfidi_down**2) * 1.94384

diff_adv = np.zeros_like(lats)
vort_500 = np.zeros_like(lats)
if all(x is not None for x in [u_400, v_400, u_700, v_700, u_500, v_500]):
    u_400_sm = ndimage.gaussian_filter(u_400, sigma=1.0)
    v_400_sm = ndimage.gaussian_filter(v_400, sigma=1.0)
    u_700_sm = ndimage.gaussian_filter(u_700, sigma=1.0)
    v_700_sm = ndimage.gaussian_filter(v_700, sigma=1.0)
    
    rel_vort_500 = mpcalc.vorticity(u_500 * units('m/s'), v_500 * units('m/s'), dx=dx, dy=dy)
    vort_500 = (rel_vort_500 + mpcalc.coriolis_parameter(lats * units.degrees)).magnitude * 1e5 
    vort_400 = mpcalc.vorticity(u_400_sm * units('m/s'), v_400_sm * units('m/s'), dx=dx, dy=dy)
    adv_400 = mpcalc.advection(vort_400, u_400_sm * units('m/s'), v_400_sm * units('m/s'), dx=dx, dy=dy)
    vort_700 = mpcalc.vorticity(u_700_sm * units('m/s'), v_700_sm * units('m/s'), dx=dx, dy=dy)
    adv_700 = mpcalc.advection(vort_700, u_700_sm * units('m/s'), v_700_sm * units('m/s'), dx=dx, dy=dy)
    diff_adv = (adv_400 - adv_700).magnitude * 1e9

fronto_925_850 = np.zeros_like(lats)
fronto_850_700 = np.zeros_like(lats)
if all(x is not None for x in [t_925, u_925, v_925, t_850, u_850, v_850, t_700, u_700, v_700]):
    theta_925 = mpcalc.potential_temperature(925 * units.hPa, t_925 * units.K)
    theta_850 = mpcalc.potential_temperature(850 * units.hPa, t_850 * units.K)
    theta_700 = mpcalc.potential_temperature(700 * units.hPa, t_700 * units.K)
    f_925 = mpcalc.frontogenesis(theta_925, u_925 * units('m/s'), v_925 * units('m/s'), dx=dx, dy=dy).magnitude * 1.08e9
    f_850 = mpcalc.frontogenesis(theta_850, u_850 * units('m/s'), v_850 * units('m/s'), dx=dx, dy=dy).magnitude * 1.08e9
    f_700 = mpcalc.frontogenesis(theta_700, u_700 * units('m/s'), v_700 * units('m/s'), dx=dx, dy=dy).magnitude * 1.08e9
    fronto_925_850 = (f_925 + f_850) / 2.0
    fronto_850_700 = (f_850 + f_700) / 2.0

mfc = np.zeros_like(lats)
if len(u_stack) > 0 and len(rh_stack) > 0:
    q_mean = mpcalc.mixing_ratio_from_relative_humidity(925 * units.hPa, np.nanmean(t_stack, axis=0) * units.K, np.nanmean(rh_stack, axis=0) * units.percent).to('g/kg')
    mfc = -mpcalc.divergence(np.nanmean(u_stack, axis=0)*units('m/s') * q_mean, np.nanmean(v_stack, axis=0)*units('m/s') * q_mean, dx=dx, dy=dy).magnitude * 10000 

trans_850 = np.zeros_like(lats)
if u_850 is not None and rh_850 is not None:
    trans_850 = mpcalc.mixing_ratio_from_relative_humidity(850 * units.hPa, t_850 * units.K, rh_850 * units.percent).magnitude * 1000 * (np.sqrt(u_850**2 + v_850**2) * 1.94384)

trans_700 = np.zeros_like(lats)
if u_700 is not None and rh_700 is not None:
    trans_700 = mpcalc.mixing_ratio_from_relative_humidity(700 * units.hPa, t_700 * units.K, rh_700 * units.percent).magnitude * 1000 * (np.sqrt(u_700**2 + v_700**2) * 1.94384)

div_250 = np.zeros_like(lats)
if u_250 is not None and v_250 is not None:
    div_250 = mpcalc.divergence(u_250 * units('m/s'), v_250 * units('m/s'), dx=dx, dy=dy).magnitude * 1e5 

print("Smoothing data and projecting...")

R_earth = 6378137.0
x_wm = R_earth * np.radians(lons)
y_wm = R_earth * np.log(np.tan(np.pi/4 + np.radians(lats)/2))

min_x, max_x = np.nanmin(x_wm), np.nanmax(x_wm)
min_y, max_y = np.nanmin(y_wm), np.nanmax(y_wm)

def process_field(data, smooth_sigma=1.0):
    if data is None: return None
    return ndimage.gaussian_filter(np.nan_to_num(data, nan=0.0), sigma=smooth_sigma)

pwat_smooth = np.where((p:=process_field(pwat, 1.0)) < 0.25, np.nan, p)
sbcape_smooth = np.where((c:=process_field(sbcape, 1.5)) < 100, np.nan, c)
mlcape_smooth = np.where((c:=process_field(mlcape, 1.5)) < 100, np.nan, c)
mucape_smooth = np.where((c:=process_field(mucape, 1.5)) < 100, np.nan, c)

pwat_diff_smooth = np.where(np.abs(p:=process_field(pwat_diff, 1.5)) < 0.1, np.nan, p)
sbcape_diff_smooth = np.where(np.abs(c:=process_field(sbcape_diff, 2.0)) < 250, np.nan, c)
mlcape_diff_smooth = np.where(np.abs(c:=process_field(mlcape_diff, 2.0)) < 250, np.nan, c)
mucape_diff_smooth = np.where(np.abs(c:=process_field(mucape_diff, 2.0)) < 250, np.nan, c)

mfc_smooth = np.where(np.abs(m:=process_field(mfc, 2.0)) < 1.0, np.nan, m)
trans_850_smooth = np.where((t:=process_field(trans_850, 1.5)) < 50, np.nan, t)
trans_700_smooth = np.where((t:=process_field(trans_700, 1.5)) < 50, np.nan, t)
vort_500_smooth = np.where((v:=process_field(vort_500, 1.5)) < 4, np.nan, v)
div_250_smooth = np.where((d:=process_field(div_250, 1.5)) < 2, np.nan, d)
lr_75_smooth = np.where((l:=process_field(lr_75, 1.5)) < 5, np.nan, l)
lr_sfc3_smooth = np.where((l:=process_field(lr_sfc3, 1.5)) < 5, np.nan, l)
spd_mean_83_smooth = np.where((s:=process_field(spd_mean_83, 1.5)) < 25, np.nan, s)
f_925_850_smooth = np.where((f:=process_field(fronto_925_850, 1.5)) < 1.0, np.nan, f)
f_850_700_smooth = np.where((f:=process_field(fronto_850_700, 1.5)) < 1.0, np.nan, f)
scp_smooth = np.where((s:=process_field(scp, 1.5)) < 1.0, np.nan, s)
spd_eff_smooth = np.where((s:=process_field(spd_eff, 1.5)) < 20, np.nan, s) 
spd_corfidi_up_smooth = np.where((s:=process_field(spd_corfidi_up, 1.5)) < 5, np.nan, s)
spd_corfidi_down_smooth = np.where((s:=process_field(spd_corfidi_down, 1.5)) < 15, np.nan, s)
diff_adv_smooth = process_field(diff_adv, 2.0) 

# --- SAVING IMAGES DIRECTLY TO DISK ---
def save_map_png(data, cmap, vmin, vmax, filename):
    if data is None: return
    fig = plt.figure(figsize=(10, 6), dpi=300, frameon=False)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    
    levels = np.linspace(vmin, vmax, 30)
    ax.contourf(x_wm, y_wm, data, levels=levels, cmap=cmap, extend='both', alpha=0.65)
    
    locator = ticker.MaxNLocator(nbins=6)
    tick_levels = locator.tick_values(vmin, vmax)
    tick_levels = tick_levels[(tick_levels >= vmin) & (tick_levels <= vmax)]
    
    CS = ax.contour(x_wm, y_wm, data, levels=tick_levels, colors='white', linewidths=0.6, alpha=0.7)
    ax.clabel(CS, inline=True, fontsize=6, fmt='%g', colors='white')
    
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    plt.savefig(f'static/{filename}', format='png', transparent=True)
    plt.close()

def save_barb_map_png(data, u, v, cmap, vmin, vmax, filename, line_color='white', contour_levels=None):
    if data is None or u is None or v is None: return
    fig = plt.figure(figsize=(10, 6), dpi=300, frameon=False)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    
    levels = np.linspace(vmin, vmax, 30)
    ax.contourf(x_wm, y_wm, data, levels=levels, cmap=cmap, extend='max', alpha=0.6)
    
    if contour_levels is not None:
        tick_levels = contour_levels
    else:
        locator = ticker.MaxNLocator(nbins=6)
        tick_levels = locator.tick_values(vmin, vmax)
        tick_levels = tick_levels[(tick_levels >= vmin) & (tick_levels <= vmax)]
    
    CS = ax.contour(x_wm, y_wm, data, levels=tick_levels, colors=line_color, linewidths=1.0, alpha=0.9)
    ax.clabel(CS, inline=True, fontsize=5, fmt='%g', colors=line_color)
    
    stride = 15
    y_idx, x_idx = np.mgrid[0:data.shape[0]:stride, 0:data.shape[1]:stride]
    u_kts = u[y_idx, x_idx] * 1.94384
    v_kts = v[y_idx, x_idx] * 1.94384 
    
    ax.barbs(x_wm[y_idx, x_idx], y_wm[y_idx, x_idx], u_kts, v_kts, length=4.5, pivot='middle', color='white', linewidth=0.8)
    
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    plt.savefig(f'static/{filename}', format='png', transparent=True)
    plt.close()

def save_diff_adv_map_png(vort_data, diff_adv_data, u, v, filename):
    if vort_data is None or diff_adv_data is None: return
    fig = plt.figure(figsize=(10, 6), dpi=300, frameon=False)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    
    levels = np.linspace(4, 30, 30)
    ax.contourf(x_wm, y_wm, vort_data, levels=levels, cmap='Greens', extend='max', alpha=0.6)
    
    pos_levels = np.arange(5, 100, 5)
    neg_levels = np.arange(-100, -4, 5)
    ax.contour(x_wm, y_wm, diff_adv_data, levels=pos_levels, colors='blue', linestyles='dashed', linewidths=1.2, alpha=0.8)
    ax.contour(x_wm, y_wm, diff_adv_data, levels=neg_levels, colors='red', linestyles='dashed', linewidths=1.2, alpha=0.8)
    
    stride = 15
    y_idx, x_idx = np.mgrid[0:vort_data.shape[0]:stride, 0:vort_data.shape[1]:stride]
    u_kts = u[y_idx, x_idx] * 1.94384
    v_kts = v[y_idx, x_idx] * 1.94384 
    ax.barbs(x_wm[y_idx, x_idx], y_wm[y_idx, x_idx], u_kts, v_kts, length=4.5, pivot='middle', color='white', linewidth=0.8)
    
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    plt.savefig(f'static/{filename}', format='png', transparent=True)
    plt.close()

def save_legend_png(cmap, vmin, vmax, title, filename, contour_levels=None):
    fig, ax = plt.subplots(figsize=(4, 0.85), dpi=100)
    fig.patch.set_alpha(0.0) 
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    
    if contour_levels is not None:
        tick_levels = contour_levels
    else:
        locator = ticker.MaxNLocator(nbins=6)
        tick_levels = locator.tick_values(vmin, vmax)
        tick_levels = tick_levels[(tick_levels >= vmin) & (tick_levels <= vmax)]
    
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=ax, orientation='horizontal', ticks=tick_levels)
    cb.set_label(title, color='white', weight='bold', fontsize=10)
    cb.ax.tick_params(colors='white', labelsize=8)
    cb.outline.set_edgecolor('white')
    
    plt.savefig(f'static/{filename}', format='png', transparent=True, bbox_inches='tight')
    plt.close()

print("Saving maps directly to static/ folder...")

max_cape = 5000
for cape_arr in [sbcape_smooth, mlcape_smooth, mucape_smooth]:
    if cape_arr is not None: max_cape = max(max_cape, np.nanmax(cape_arr))
max_cape = int(np.ceil(max_cape / 1000) * 1000)

# Standard Base Fields
save_map_png(pwat_smooth, 'nipy_spectral', 0.25, 2.75, 'rap_pwat.png')
save_map_png(sbcape_smooth, 'hot_r', 100, max_cape, 'rap_sbcape.png')
save_map_png(mlcape_smooth, 'hot_r', 100, max_cape, 'rap_mlcape.png')
save_map_png(mucape_smooth, 'hot_r', 100, max_cape, 'rap_mucape.png')

# New Difference Fields (Centered on 0 using Divergent Colormaps)
save_map_png(pwat_diff_smooth, 'BrBG', -1.0, 1.0, 'rap_pwat_diff.png')
save_map_png(sbcape_diff_smooth, 'RdBu_r', -2000, 2000, 'rap_sbcape_diff.png')
save_map_png(mlcape_diff_smooth, 'RdBu_r', -2000, 2000, 'rap_mlcape_diff.png')
save_map_png(mucape_diff_smooth, 'RdBu_r', -2000, 2000, 'rap_mucape_diff.png')

# Remaining Fields
save_map_png(mfc_smooth, 'BrBG', -10, 10, 'rap_mfc.png')
save_map_png(lr_75_smooth, 'YlOrRd', 5, 10, 'rap_lr_75.png')
save_map_png(lr_sfc3_smooth, 'YlOrRd', 5, 10, 'rap_lr_sfc3.png')
save_map_png(f_925_850_smooth, 'gnuplot2_r', 1, 10, 'rap_f925_850.png')
save_map_png(f_850_700_smooth, 'gnuplot2_r', 1, 10, 'rap_f850_700.png')
save_map_png(scp_smooth, 'YlOrRd', 1, 20, 'rap_scp.png')

save_barb_map_png(trans_850_smooth, u_850, v_850, 'YlGnBu', 50, 400, 'rap_trans850.png')
save_barb_map_png(trans_700_smooth, u_700, v_700, 'YlGnBu', 50, 400, 'rap_trans700.png')
save_barb_map_png(vort_500_smooth, u_500, v_500, 'YlOrRd', 4, 30, 'rap_vort500.png')
save_barb_map_png(div_250_smooth, u_250, v_250, 'PuRd', 2, 10, 'rap_div250.png')
save_barb_map_png(spd_mean_83_smooth, u_mean_83, v_mean_83, 'Blues', 30, 100, 'rap_mean_wind.png', line_color='blue', contour_levels=np.arange(30, 110, 10))
save_barb_map_png(spd_eff_smooth, u_eff, v_eff, 'Purples', 25, 80, 'rap_eff_shear.png', line_color='indigo', contour_levels=np.arange(30, 90, 10))
save_barb_map_png(spd_corfidi_up_smooth, u_corfidi_up, v_corfidi_up, 'PuBu', 10, 60, 'rap_corfidi_up.png', line_color='navy', contour_levels=np.arange(10, 70, 10))
save_barb_map_png(spd_corfidi_down_smooth, u_corfidi_down, v_corfidi_down, 'OrRd', 20, 80, 'rap_corfidi_down.png', line_color='darkred', contour_levels=np.arange(20, 90, 10))

save_diff_adv_map_png(vort_500_smooth, diff_adv_smooth, u_500, v_500, 'rap_diff_adv.png')

# Standard Legends
save_legend_png('nipy_spectral', 0.25, 2.75, "Precipitable Water (inches)", 'leg_pwat.png')
save_legend_png('hot_r', 100, max_cape, "CAPE (J/kg)", 'leg_cape.png')
save_legend_png('BrBG', -10, 10, "Mean BL Moisture Convergence", 'leg_mfc.png')
save_legend_png('YlGnBu', 50, 400, "Moisture Transport Magnitude", 'leg_trans.png')
save_legend_png('YlOrRd', 4, 30, "500mb Absolute Vorticity (x 10^5 s^-1)", 'leg_vort.png')
save_legend_png('PuRd', 2, 10, "250mb Divergence (x 10^5 s^-1)", 'leg_div.png')
save_legend_png('YlOrRd', 5, 10, "700-500mb Lapse Rate (°C/km)", 'leg_lr75.png')
save_legend_png('YlOrRd', 5, 10, "Sfc-3km Lapse Rate (°C/km)", 'leg_lrsfc3.png')
save_legend_png('Blues', 30, 100, "850-300mb Mean Layer Wind (knots)", 'leg_mean_wind.png', contour_levels=np.arange(30, 110, 10))
save_legend_png('Greens', 4, 30, "500mb Absolute Vorticity (Fill)\n700-400mb Differential Advection (Lines)", 'leg_diff_adv.png')
save_legend_png('gnuplot2_r', 1, 10, "Frontogenesis (K / 100km / 3hr)", 'leg_fronto.png')
save_legend_png('YlOrRd', 1, 20, "Supercell Composite Parameter (SCP)", 'leg_scp.png')
save_legend_png('Purples', 25, 80, "Effective Bulk Wind Shear (knots)", 'leg_eff_shear.png', contour_levels=np.arange(30, 90, 10))
save_legend_png('PuBu', 10, 60, "Corfidi Upwind Vector Magnitude (knots)", 'leg_corfidi_up.png', contour_levels=np.arange(10, 70, 10))
save_legend_png('OrRd', 20, 80, "Corfidi Downwind Vector Magnitude (knots)", 'leg_corfidi_down.png', contour_levels=np.arange(20, 90, 10))

# New Difference Legends
save_legend_png('BrBG', -1.0, 1.0, "3-Hour PWAT Change (inches)", 'leg_pwat_diff.png')
save_legend_png('RdBu_r', -2000, 2000, "3-Hour CAPE Change (J/kg)", 'leg_cape_diff.png')

print("Exporting exact bounding box and metadata to JSON...")
bounds = [
    [float(np.nanmin(lats)), float(np.nanmin(lons))],
    [float(np.nanmax(lats)), float(np.nanmax(lons))]
]

with open("static/rap_metadata.json", "w") as f:
    json.dump({
        "valid_time": valid_time_str,
        "bounds": bounds
    }, f)

print("Process Complete!")
