"""Scientific review figure from validated RSM suite PNGs and geographic state outlines."""
import argparse,json,math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from tools.sport_rsm_suite import COLORS,EDGES

def main():
    p=argparse.ArgumentParser();p.add_argument('--suite-dir',type=Path,required=True);p.add_argument('--states',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=json.loads((a.suite_dir/'metadata.json').read_text());states=json.loads(a.states.read_text())
    canvas=Image.new('RGB',(1480,680),'#111923');draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18);large=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)
    draw.text((20,15),'NASA SPoRT-LIS • Relative Soil Moisture',font=large,fill='white')
    draw.text((20,52),'Valid '+m['active']['valid_time']+' | 4,000 × 2,538 source overlays | Bilinear display reprojection',font=font,fill='#c6d6e5')
    def merc(lat):return math.log(math.tan(math.pi/4+math.radians(lat)/2))
    for n,d in enumerate(['10','200']):
        product=m['active']['products'][d];im=Image.open(a.suite_dir/product['image']['path']).convert('RGBA').resize((720,457),Image.Resampling.NEAREST)
        bg=Image.new('RGBA',im.size,'#27323d');bg.alpha_composite(im);pen=ImageDraw.Draw(bg);b=product['image']['bounds']
        def point(lon,lat):return ((lon-b[0][1])/(b[1][1]-b[0][1])*720,(merc(b[1][0])-merc(lat))/(merc(b[1][0])-merc(b[0][0]))*457)
        for f in states['features']:
            g=f['geometry'];polys=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
            for poly in polys:
                for ring in poly:pen.line([point(*xy[:2]) for xy in ring],fill='#e7edf2',width=1)
        x=15+n*740;canvas.paste(bg,(x,115));draw.text((x,86),'Surface: 0–10 cm' if d=='10' else 'Integrated column: 0–200 cm',font=font,fill='white')
    for i,c in enumerate(COLORS):
        x=20+i*180;sw=Image.new('RGBA',(28,18),'#27323d');sw.alpha_composite(Image.new('RGBA',(28,18),tuple(int(v) for v in c)));canvas.paste(sw,(x,590));draw.text((x+35,587),f'{EDGES[i]}–'+('100%' if i==7 else f'<{EDGES[i+1]}%'),font=font,fill='white')
    draw.text((20,623),'0% = wilting point • 100% = saturation • Missing cells transparent • Not a percentile or flood probability',font=font,fill='white')
    draw.text((20,651),'Nominal 3-km model data. Extra display pixels add no scientific resolution. Review only.',font=font,fill='#c6d6e5')
    a.output.parent.mkdir(parents=True,exist_ok=True);canvas.save(a.output)
if __name__=='__main__':main()
