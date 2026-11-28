"""Render GDI; RAP uses masked scalar bilinear interpolation for display only."""
import argparse,json,pathlib,hashlib
import numpy as np
from scipy.spatial import cKDTree
from pyproj import Transformer, CRS
from PIL import Image
from contours import contour_image,levels_for,CONTOUR_STYLE
from matplotlib.colors import to_rgba
from render import COLORS,WIDTH,HEIGHT,BOUNDS
DIFF=['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7','#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']

def xyz(lon,lat):
 lo,la=np.deg2rad(lon),np.deg2rad(lat);return np.column_stack([(np.cos(la)*np.cos(lo)).ravel(),(np.cos(la)*np.sin(lo)).ravel(),np.sin(la).ravel()])

def bilinear_sample(field,xx,yy):
 """Interpolate four finite native cells; never fill masked terrain/domain gaps."""
 ny,nx=field.shape
 inside=(xx>=0)&(xx<=nx-1)&(yy>=0)&(yy<=ny-1)
 ix=np.clip(np.floor(xx).astype(int),0,nx-2);iy=np.clip(np.floor(yy).astype(int),0,ny-2)
 dx=np.clip(xx-ix,0,1);dy=np.clip(yy-iy,0,1)
 cells=[field[iy,ix],field[iy,ix+1],field[iy+1,ix],field[iy+1,ix+1]]
 good=inside & np.logical_and.reduce([np.isfinite(a) for a in cells])
 value=cells[0]*(1-dx)*(1-dy)+cells[1]*dx*(1-dy)+cells[2]*(1-dx)*dy+cells[3]*dx*dy
 return np.where(good,value,np.nan)

def rap_coordinates(native_lon,native_lat,display_lon,display_lat):
 native=CRS.from_proj4('+proj=lcc +lat_1=25 +lat_2=25 +lat_0=25 +lon_0=-95 +R=6371229 +units=m')
 project=Transformer.from_crs(4326,native,always_xy=True)
 gx,gy=project.transform(native_lon,native_lat);iy,ix=np.indices(native_lat.shape)
 sel=(slice(None,None,10),slice(None,None,10))
 design=np.column_stack([gx[sel].ravel(),gy[sel].ravel(),np.ones(gx[sel].size)])
 target=np.column_stack([ix[sel].ravel(),iy[sel].ravel()]);coef=np.linalg.lstsq(design,target,rcond=None)[0]
 if np.max(np.abs(design@coef-target))>.01:raise ValueError('RAP grid does not match its Lambert projection')
 px,py=project.transform(display_lon,display_lat)
 return px*coef[0,0]+py*coef[1,0]+coef[2,0],px*coef[0,1]+py*coef[1,1]+coef[2,1]
def render(input_dir,public):
 root,public=pathlib.Path(input_dir),pathlib.Path(public);spec=json.loads((root/'suite.json').read_text());fields=np.load(root/'fields.npz')
 digest=hashlib.sha256(b'labeled-contours-v1'+(root/'fields.npz').read_bytes()+(root/'suite.json').read_bytes()).hexdigest()[:12];generation=spec['cycle'].replace('-','').replace(':','')[:11].replace('T','')+'-'+digest+'-v1'
 dest=public/'generations'/generation;dest.mkdir(parents=True,exist_ok=True)
 merc=Transformer.from_crs(4326,3857,always_xy=True);w,s=merc.transform(-125,24);e,n=merc.transform(-66,50)
 x,y=np.meshgrid(w+(np.arange(WIDTH)+.5)*(e-w)/WIDTH,n-(np.arange(HEIGHT)+.5)*(n-s)/HEIGHT);lon,lat=Transformer.from_crs(3857,4326,always_xy=True).transform(x,y)
 interpolate=spec.get('display_rendering')=='rap_scalar_bilinear_v1'
 if interpolate:
  if spec.get('model')!='rap':raise ValueError('Bilinear display is restricted to RAP')
  xx,yy=rap_coordinates(fields['longitude'],fields['latitude'],lon,lat)
 else:
  distance,index=cKDTree(xyz(fields['longitude'],fields['latitude'])).query(xyz(lon,lat));valid=distance*6371229<spec['native_spacing_km']*1000*.8
 assets={}
 for key,product in spec['products'].items():
  if interpolate:a=bilinear_sample(fields[key],xx,yy)
  else:
   a=fields[key].ravel()[index].reshape(HEIGHT,WIDTH);a=np.where(valid.reshape(HEIGHT,WIDTH),a,np.nan)
  colors=product.get('colors',COLORS);edges=product.get('edges',list(range(-30,60,5)));rgba=np.array([[round(x*255) for x in to_rgba(c)] for c in colors],dtype='uint8')
  ix=np.clip(np.searchsorted(edges,np.nan_to_num(a,nan=-999),side='right')-1,0,len(colors)-1);pixels=rgba[ix];pixels[~np.isfinite(a)]=0
  for numbers in (False,True):
   name=key+('_numbers' if numbers else '')
   if numbers:
    levels=[10,25,50,75,90] if '%' in product.get('unit','') else levels_for(key)
    im=contour_image(a,levels)
   else:im=Image.fromarray(pixels)
   path=dest/(name+'.png');im.save(path,optimize=True);assets[name]={'path':str(path.relative_to(public)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
  product['colors']=colors
  product['edges']=edges
  product.setdefault('scale_labels', ['−30','−15','0','15','30','45','≥55'] if colors==COLORS else [format(float(v),'.3g') for v in edges])
 metadata={**spec,'overlay_type':CONTOUR_STYLE,'schema':'gdi_named_suite_v1','generation':generation,'assets':assets,'width':WIDTH,'height':HEIGHT,'bounds':BOUNDS,'crs':'EPSG:3857','resampling':'masked_bilinear' if interpolate else 'nearest'}
 (dest/'provenance.json').write_text(json.dumps(spec,indent=2));tmp=public/'metadata.tmp';tmp.write_text(json.dumps(metadata,indent=2));tmp.replace(public/'metadata.json');print('Rendered',generation,len(assets),'assets',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--public',required=True);a=p.parse_args();render(a.input,a.public)
