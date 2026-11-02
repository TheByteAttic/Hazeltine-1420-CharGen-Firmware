# Copyright (c) 2026 by The Byte Attic B.V.
"""Rev B: remove the solder jumpers JP1/JP2 from an already routed layout_<variant>.json and hard-wire
the DM8678 pin assignment (the only one needed: both original chips use it).

Deliberately NOT a re-route.  The routed copper is left exactly as it was, except for:
  * the six jumper pads are deleted (JP1 A/B/C, JP2 A/B/C);
  * the former jumper bridges JP1 C-A and JP2 C-A become short top-layer tracks between the
    track ends that used to land on those pads (VOUT -> socket pin 11, latched A7 -> /OE);
  * the branch of net PIN11 that only served pad JP2-B (the DM86S64 option) is removed, i.e. the
    tracks and vias that are left dangling once that pad is gone;
  * the PIN12 track that passed through pad JP1-B continues as plain track (both halves already
    meet at the pad centre);
  * net names: VOUT is merged into PIN11, nOE into LA7 (they are the same copper now);
  * teardrops and the bottom GND pour are regenerated for the changed geometry with the same
    code and parameters as cleanup.py (identical everywhere else - checked by compare()).
Usage: python3 dejumper.py U|L
"""
import json, math, sys
from cleanup import Cleaner
from pour import make_pour, mask_polygons, POUR_NETS

RENAME = {'VOUT': 'PIN11', 'nOE': 'LA7'}
EPS = 1e-3

def same(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1]) < EPS

def point_on_seg(p, a, b, tol):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(px - ax, py - ay) <= tol
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= tol

def anchored(p, net, layer, tracks, vias, pads, self_idx):
    """True if point p (end of track self_idx) touches a pad, a via or another track of the net."""
    for pd in pads:
        if pd['net'] == net and layer in pd['layers']:
            hw, hh = (pd['size'][0] / 2, pd['size'][1] / 2) if pd['shape'] == 'smd' else (pd['size'] / 2, pd['size'] / 2)
            if abs(p[0] - pd['x']) <= hw + EPS and abs(p[1] - pd['y']) <= hh + EPS:
                return True
    for v in vias:
        if v['net'] == net and same(p, (v['x'], v['y'])):
            return True
    for j, t in enumerate(tracks):
        if j == self_idx or t['net'] != net or t['layer'] != layer:
            continue
        for a, b in zip(t['pts'], t['pts'][1:]):
            if point_on_seg(p, a, b, t['w'] / 2 + EPS):
                return True
    return False

def via_users(v, tracks):
    n = 0
    for t in tracks:
        if t['net'] != v['net']:
            continue
        for a, b in zip(t['pts'], t['pts'][1:]):
            if point_on_seg((v['x'], v['y']), a, b, t['w'] / 2 + EPS):
                n += 1; break
    return n

def prune_dangling(tracks, vias, pads, nets):
    """Remove whole tracks with a free end, and vias used by fewer than two tracks, on the given nets."""
    removed_t, removed_v = [], []
    changed = True
    while changed:
        changed = False
        for i, t in enumerate(tracks):
            if t['net'] not in nets:
                continue
            for end in (t['pts'][0], t['pts'][-1]):
                if not anchored(end, t['net'], t['layer'], tracks, vias, pads, i):
                    removed_t.append(tracks.pop(i)); changed = True
                    break
            if changed:
                break
        if changed:
            continue
        for i, v in enumerate(vias):
            if v['net'] in nets and via_users(v, tracks) < 2:
                removed_v.append(vias.pop(i)); changed = True
                break
    return removed_t, removed_v

def run(variant):
    d = json.load(open(f'layout_{variant}.json'))
    old = json.loads(json.dumps(d))
    jp = {(p['ref'], p['pin']): (p['x'], p['y']) for p in d['pads'] if p['ref'] in ('JP1', 'JP2')}
    assert len(jp) == 6, 'jumper pads not found - already converted?'
    # 1. pads
    d['pads'] = [p for p in d['pads'] if p['ref'] not in ('JP1', 'JP2')]
    # 2. net names
    for coll in ('pads', 'tracks', 'vias'):
        for it in d[coll]:
            it['net'] = RENAME.get(it['net'], it['net'])
    # 3. the two former bridges as tracks (0.20 mm, top), pad centre to pad centre
    def bridge(a, b, net):
        assert abs(a[1] - b[1]) < EPS
        d['tracks'].append(dict(net=net, layer='top', pts=[list(a), list(b)], w=0.20))
    bridge(jp[('JP1', 'C')], jp[('JP1', 'A')], 'PIN11')
    bridge(jp[('JP2', 'C')], jp[('JP2', 'A')], 'LA7')
    # 4. prune what only served the deleted pads (expected: the PIN11 branch to JP2-B)
    rt, rv = prune_dangling(d['tracks'], d['vias'], d['pads'], {'PIN11', 'LA7', 'PIN12'})
    # 5. teardrops and pour, exactly as cleanup.run() does
    del d['teardrops']
    c = Cleaner(d)
    c.add_teardrops()
    d['tracks'] = [dict(net=t['net'], layer=t['layer'], pts=[list(p) for p in t['pts']], w=t['w']) for t in c.tracks]
    d['teardrops'] = [dict(net=td['net'], layer=td['layer'], pts=[list(p) for p in td['pts']]) for td in c.teardrops]
    pseudo = d['tracks'] + [dict(net=td['net'], layer=td['layer'], pts=[list(p) for p in td['pts']] + [list(td['pts'][0])], w=0.05) for td in c.teardrops]
    pours = {}
    for layer, net in POUR_NETS.items():
        R, mask = make_pour(d, layer, net, tracks=pseudo)
        outers, holes = mask_polygons(R, mask)
        pours[layer] = dict(net=net, outers=outers, holes=holes, segs=[])
    d['pours'] = pours
    json.dump(d, open(f'layout_{variant}.json', 'w'))
    report(variant, old, d, rt, rv, jp)

def report(variant, old, new, rt, rv, jp):
    def key(t):
        return (t['net'], t['layer'], tuple(tuple(round(x, 4) for x in p) for p in t['pts']), t['w'])
    def tdkey(t):
        return (t['net'], t['layer'], tuple(tuple(round(x, 3) for x in p) for p in t['pts']))
    ren = lambda n: RENAME.get(n, n)
    ot = {key(dict(t, net=ren(t['net']))) for t in old['tracks']}
    nt = {key(t) for t in new['tracks']}
    otd = {tdkey(dict(t, net=ren(t['net']))) for t in old['teardrops']}
    ntd = {tdkey(t) for t in new['teardrops']}
    print(f'[{variant}] pads removed: {sorted(jp)}')
    print(f'[{variant}] tracks removed ({len(rt)}):')
    for t in rt: print('    ', t['net'], t['layer'], [(round(x, 3), round(y, 3)) for x, y in t['pts']])
    print(f'[{variant}] vias removed ({len(rv)}):', [(v['net'], round(v['x'], 3), round(v['y'], 3)) for v in rv])
    print(f'[{variant}] tracks added:', [k for k in nt - ot if k not in {key(t) for t in rt}])
    assert ot - nt == {key(dict(t, net=ren(t['net']))) for t in rt}, 'unexpected track change'
    # teardrops: the only differences must lie within 2 mm of a deleted pad or via
    hot = list(jp.values()) + [(v['x'], v['y']) for v in rv]
    def near(td):
        return any(math.hypot(p[0] - hx, p[1] - hy) < 2.0 for p in td[2] for (hx, hy) in hot)
    far_diff = [t for t in (otd ^ ntd) if not near(t)]
    print(f'[{variant}] teardrops: {len(otd)} -> {len(ntd)}; differences away from the changed spots: {len(far_diff)}')
    assert not far_diff, far_diff
    print(f'[{variant}] pads {len(old["pads"])} -> {len(new["pads"])}, tracks {len(old["tracks"])} -> {len(new["tracks"])}, vias {len(old["vias"])} -> {len(new["vias"])}')

if __name__ == '__main__':
    for v in sys.argv[1:] or ['U', 'L']:
        run(v)
