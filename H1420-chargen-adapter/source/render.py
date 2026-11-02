# Copyright (c) 2026 by The Byte Attic B.V.
import json, sys, numpy as np
from PIL import Image
import check
from check import parse_gerber, Raster
check.RES=0.01
for v in sys.argv[1:]:
    name='h1420-chargen-U26-upper' if v=='U' else 'h1420-chargen-U25-lower'
    d=json.load(open(f'layout_{v}.json')); poly=d['outline']
    xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
    R=Raster(min(xs),min(ys),max(xs),max(ys))
    layers={}
    for suf in ('B_Cu','F_Cu','F_Silkscreen','B_Silkscreen','Edge_Cuts','F_Mask','B_Mask'):
        aps,items=parse_gerber(f'gerber_{v}/{name}-{suf}.gbr')
        layers[suf]=np.array(R.draw_items(aps,items),bool)
    from check import parse_drill
    from PIL import ImageDraw
    holes=parse_drill(f'gerber_{v}/{name}-PTH.drl')
    hm=Image.new('1',(R.W,R.H),0); dr=ImageDraw.Draw(hm)
    for (x,y,dia) in holes:
        cx,cy=R.px(x,y); rr=dia/2/check.RES; dr.ellipse([cx-rr,cy-rr,cx+rr,cy+rr],fill=1)
    hm=np.array(hm,bool)
    a=np.full((R.H,R.W,3),(20,60,30),np.uint8)
    a[layers['B_Cu']]=(40,90,160); a[layers['F_Cu']]=(190,60,50); a[layers['F_Mask']&layers['F_Cu']]=(220,190,90)
    a[layers['F_Silkscreen']]=(255,255,255); a[layers['Edge_Cuts']]=(255,255,0); a[hm]=(10,10,10)
    im=Image.fromarray(a); im.resize((im.width//3,im.height//3),Image.LANCZOS).save(f'render_top_{v}.png')
    b=np.full((R.H,R.W,3),(20,60,30),np.uint8)
    b[layers['B_Cu']]=(40,90,160); b[layers['B_Mask']&layers['B_Cu']]=(220,190,90); b[layers['B_Silkscreen']]=(255,255,255); b[layers['Edge_Cuts']]=(255,255,0); b[hm]=(10,10,10)
    im=Image.fromarray(b).transpose(Image.FLIP_LEFT_RIGHT); im.resize((im.width//3,im.height//3),Image.LANCZOS).save(f'render_bot_{v}.png')
    # copper-only views without the pour: draw from json
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle, Polygon
    for L in ('top','bot'):
        W=max(xs)-min(xs); H=max(ys)-min(ys)
        fig,ax=plt.subplots(figsize=(W/5,H/5))
        ax.add_patch(Polygon(poly,closed=True,fill=False,lw=1,ec='k'))
        col='#c0392b' if L=='top' else '#2471a3'
        for p in d['pads']:
            if L not in p['layers']: continue
            if p['shape']=='smd': w,h=p['size']; ax.add_patch(Rectangle((p['x']-w/2,p['y']-h/2),w,h,fc='#d4ac0d',ec='none'))
            elif p['shape']=='rect': s=p['size']; ax.add_patch(Rectangle((p['x']-s/2,p['y']-s/2),s,s,fc='#d4ac0d',ec='none',zorder=1))
            else: ax.add_patch(Circle((p['x'],p['y']),p['size']/2,fc='#d4ac0d',ec='none',zorder=1))
        for t in d['tracks']:
            if t['layer']!=L: continue
            px,py=zip(*t['pts']); ax.plot(px,py,color=col,lw=t['w']*9,solid_capstyle='round',solid_joinstyle='round')
        for td in d['teardrops']:
            if td['layer']==L: ax.add_patch(Polygon(td['pts'],closed=True,fc=col,ec='none'))
        for vv in d['vias']: ax.add_patch(Circle((vv['x'],vv['y']),0.3,fc=col,ec='none')); ax.add_patch(Circle((vv['x'],vv['y']),0.15,fc='w',ec='none',zorder=5))
        for p in d['pads']:
            if p['shape']!='smd': ax.add_patch(Circle((p['x'],p['y']),p['hole']/2,fc='w',ec='none',zorder=5))
        ax.set_xlim(min(xs)-1,max(xs)+1); ax.set_ylim(min(ys)-1,max(ys)+1); ax.set_aspect('equal'); ax.axis('off')
        fig.savefig(f'tracks_{L}_{v}.png',dpi=170,bbox_inches='tight'); plt.close(fig)
print('ok')
