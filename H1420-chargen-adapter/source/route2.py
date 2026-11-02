# Copyright (c) 2026 by The Byte Attic B.V.
"""PathFinder routing driver with power pours: python3 route2.py U|L [iters]"""
import json, sys, time
import numpy as np
from router2 import PFRouter, TRACE_W, POWER_W
from design import NETS, BUS_NETS
from pour import make_pour, cells_inside, scanlines, POUR_NETS

POWER = ['GND', 'VCC']
def signal_order():
    first = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'ROW0', 'ROW1', 'ROW2', 'ROW3',
             'LA0', 'LA1', 'LA2', 'LA3', 'LA4', 'LA5', 'PU1', 'PU26', 'PU27', 'SER', 'VOUT', 'nOE', 'LA7']
    rest = [n for n in NETS if n not in first and n not in POWER and n not in BUS_NETS]
    return list(BUS_NETS) + first + rest

def layout_dict(r, widths, variant, extra=None):
    tracks, vias = r.geometry(widths)
    d = dict(variant=variant, outline=r.poly,
        pads=[dict(ref=p.ref, pin=p.pin, net=p.net, x=p.x, y=p.y, hole=p.hole, size=p.size, shape=p.shape, layers=list(p.lay)) for p in r.pads],
        tracks=[dict(net=t.net, layer=t.layer, pts=t.pts, w=t.w) for t in tracks],
        vias=[dict(net=v.net, x=v.x, y=v.y) for v in vias])
    if extra: d.update(extra)
    return d

def build_pours(r, d):
    pours = {}
    masks = {}
    for layer, net in POUR_NETS.items():
        R, mask = make_pour(d, layer, net)
        masks[layer] = (R, mask)
        pours[layer] = dict(net=net, segs=scanlines(R, mask))
    return pours, masks

def main(variant, iters=40):
    r = PFRouter(variant)
    widths = {n: POWER_W for n in POWER}
    t0 = time.time()
    print('phase 1: all nets (power routed as wide traces)')
    ok1 = r.run(POWER + signal_order(), widths, iters=iters)
    import pickle; pickle.dump(r, open(f'state1_{variant}.pkl', 'wb'))
    d = layout_dict(r, widths, variant)
    print('phase 2: GND pour around everything')
    pours, masks = build_pours(r, d)
    d['pours'] = pours
    d['ok'] = bool(ok1)
    print(f'[{variant}] {"OK" if d["ok"] else "FAILED"} in {time.time()-t0:.0f}s: {len(d["tracks"])} tracks, {len(d["vias"])} vias')
    json.dump(d, open(f'layout_{variant}.json', 'w'))
    return d['ok']

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'U', int(sys.argv[2]) if len(sys.argv) > 2 else 40)
