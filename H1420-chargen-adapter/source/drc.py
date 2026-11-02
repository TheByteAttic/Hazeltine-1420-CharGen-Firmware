# Copyright (c) 2026 by The Byte Attic B.V.
"""Design-rule check of the exported Gerber/drill set against JLCPCB's 2-layer capabilities.

Everything is measured on the manufacturing files themselves (rasterised at 0.0125 mm, apertures
read exactly); the layout json is used only to know which net each pad belongs to (for the
different-net clearance rule) and for the outline.

Rules (JLCPCB 2-layer, 1 oz):                            checked as
  min trace width               0.127 mm                 aperture widths + raster opening of all copper
  min clearance (other net)     0.127 mm                 EDT between net masks
  min drill (via)               0.30 mm                  drill file
  min via diameter              0.50 mm  (ring >= 0.13)  copper flash around each via hole
  min annular ring PTH pad      0.13 mm                  pad copper around each hole
  hole to hole (edge)           0.50 mm                  drill file, all pairs
  hole to copper of other net   0.254 mm                 EDT from other-net copper to hole edge
  copper to board edge          0.30 mm                  EDT from outline
  hole to board edge            0.50 mm (0.3 non-plated) drill vs outline
  solder-mask bridge            0.20 mm                  raster closing of mask openings
  silkscreen line width         0.153 mm                 aperture widths + raster opening of silk
  silkscreen over mask opening  0 (clipped by JLC)       raster overlap silk & mask
  silkscreen to board edge      0.30 mm

    python3 drc.py U      (or L)
"""
import json, sys, math
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
import check as C

RES = 0.0125
RULES = dict(trace=0.127, clear=0.127, drill=0.30, via_dia=0.50, ring=0.13, hole_hole=0.50, hole_cu=0.254,
             cu_edge=0.30, hole_edge=0.50, mask_bridge=0.20, silk_w=0.153, silk_edge=0.30)

def disk(r_mm):
    r = max(1, int(round(r_mm / RES)))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r * r

def min_feature(mask, limit, exclude=None):
    """Return the area (mm^2) of features narrower than `limit` (opening test).  `exclude` masks
    regions whose sharp corners are legitimate (rectangular pads)."""
    if not mask.any(): return 0.0
    o = ndimage.binary_opening(mask, structure=disk(limit / 2 * 0.98))
    lost = mask & ~o
    if exclude is not None:
        lost &= ~exclude
    # ignore single-pixel rounding at feature ends: require a blob of >= 4 px
    lab, n = ndimage.label(lost)
    if not n: return 0.0
    sizes = ndimage.sum(lost, lab, range(1, n + 1))
    return float(sum(s for s in sizes if s >= 6)) * RES * RES

def drc(variant):
    C.RES = RES
    name = f'h1420-chargen-{"U26-upper" if variant == "U" else "U25-lower"}'
    gdir = f'gerber_{variant}'
    d = json.load(open(f'layout_{variant}.json'))
    poly = d['outline']
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    R = C.Raster(min(xs), min(ys), max(xs), max(ys))
    img = {}; aps_all = {}
    for key in ('F_Cu', 'B_Cu', 'F_Mask', 'B_Mask', 'F_Silkscreen', 'B_Silkscreen'):
        aps, items = C.parse_gerber(f'{gdir}/{name}-{key}.gbr')
        aps_all[key] = (aps, items)
        img[key] = np.array(R.draw_items(aps, items), bool)
    holes = C.parse_drill(f'{gdir}/{name}-PTH.drl')
    outline_img = Image.new('1', (R.W, R.H), 0)
    ImageDraw.Draw(outline_img).polygon([R.px(x, y) for (x, y) in poly], fill=1)
    inside = np.array(outline_img, bool)
    edge_d = ndimage.distance_transform_edt(inside) * RES
    # rectangular pad areas (their corners are legitimately sharp)
    padrect = {'F_Cu': np.zeros((R.H, R.W), bool), 'B_Cu': np.zeros((R.H, R.W), bool)}
    for p in d['pads']:
        if p['shape'] == 'smd':
            hw, hh = p['size'][0] / 2, p['size'][1] / 2
        elif p['shape'] == 'rect':
            hw = hh = p['size'] / 2
        else:
            continue
        for L in p['layers']:
            key = 'F_Cu' if L == 'top' else 'B_Cu'
            x0, y0 = R.px(p['x'] - hw - 0.03, p['y'] + hh + 0.03); x1, y1 = R.px(p['x'] + hw + 0.03, p['y'] - hh - 0.03)
            padrect[key][int(y0):int(y1) + 1, int(x0):int(x1) + 1] = True
    errors = []; report = []
    def rule(name, value, limit, ok=None):
        ok = (value >= limit) if ok is None else ok
        report.append(f'  {"ok  " if ok else "FAIL"} {name:38s} {value:8.3f} mm   (limit {limit})')
        if not ok: errors.append(name)

    # ---- trace width: apertures used for lines, and raster opening on all copper
    for key in ('F_Cu', 'B_Cu'):
        aps, items = aps_all[key]
        ws = [aps[it[1]][1][0] for it in items if it[0] == 'line']
        rule(f'{key} min line aperture', min(ws), RULES['trace'])
        thin = min_feature(img[key] & inside, RULES['trace'], padrect[key])
        rule(f'{key} copper thinner than 0.127 (area)', thin, 0.0, ok=thin == 0.0)

    # ---- nets: label copper, link through holes, assign nets from pads
    lab = {}; nlab = {}
    for key in ('F_Cu', 'B_Cu'):
        lab[key], nlab[key] = ndimage.label(img[key], structure=np.ones((3, 3)))
    parent = {}
    def find(a):
        while parent.get(a, a) != a: a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    def at(x, y):
        px, py = R.px(x, y); return int(round(py)), int(round(px))
    for (x, y, dia) in holes:
        i, j = at(x, y)
        if lab['F_Cu'][i, j] and lab['B_Cu'][i, j]:
            union(('F_Cu', lab['F_Cu'][i, j]), ('B_Cu', lab['B_Cu'][i, j]))
    comp_net = {}
    for p in d['pads']:
        if not p['net']: continue
        for L in p['layers']:
            key = 'F_Cu' if L == 'top' else 'B_Cu'
            i, j = at(p['x'], p['y'])
            if lab[key][i, j]:
                comp_net[find((key, lab[key][i, j]))] = p['net']
    netimg = {}
    for key in ('F_Cu', 'B_Cu'):
        m = np.zeros(lab[key].shape, np.int32)
        names = []
        for l in range(1, nlab[key] + 1):
            n = comp_net.get(find((key, l)))
            if n:
                if n not in names: names.append(n)
                m[lab[key] == l] = names.index(n) + 1
        netimg[key] = (m, names)

    # ---- clearance between different nets, and hole edge to other-net copper
    min_clear = 99; min_hole_cu = 99
    for key in ('F_Cu', 'B_Cu'):
        m, names = netimg[key]
        for k in range(len(names)):
            mine = m == k + 1
            others = (m > 0) & ~mine
            if not others.any(): continue
            dist = ndimage.distance_transform_edt(~mine) * RES
            min_clear = min(min_clear, float(dist[others].min()))
            # holes belonging to other nets: distance from hole edge to this net's copper
            for (x, y, dia) in holes:
                i, j = at(x, y)
                if m[i, j] and m[i, j] != k + 1:
                    min_hole_cu = min(min_hole_cu, float(dist[i, j]) - dia / 2)
    rule('copper clearance between nets', min_clear, RULES['clear'])
    rule('hole edge to other-net copper', min_hole_cu, RULES['hole_cu'])

    # ---- drills, rings, hole spacing, hole to edge
    rule('smallest drill', min(h[2] for h in holes), RULES['drill'])
    min_ring = 99; min_via = 99
    via_set = {(round(v['x'], 3), round(v['y'], 3)) for v in d['vias']}
    for key in ('F_Cu', 'B_Cu'):
        dist_out = ndimage.distance_transform_edt(img[key]) * RES     # distance to nearest non-copper
        for (x, y, dia) in holes:
            i, j = at(x, y)
            ring = float(dist_out[i, j]) - dia / 2                      # copper radius around the hole centre
            min_ring = min(min_ring, ring)
            if (round(x, 3), round(y, 3)) in via_set:
                min_via = min(min_via, 2 * float(dist_out[i, j]))
    rule('annular ring (all holes, both layers)', min_ring, RULES['ring'])
    rule('via outer diameter', min_via, RULES['via_dia'])
    hh = 99
    H = np.array([(x, y, dia) for (x, y, dia) in holes])
    for a in range(len(H)):
        dx = H[a + 1:, 0] - H[a, 0]; dy = H[a + 1:, 1] - H[a, 1]
        if len(dx):
            e = np.sqrt(dx * dx + dy * dy) - (H[a + 1:, 2] + H[a, 2]) / 2
            hh = min(hh, float(e.min()))
    rule('hole to hole (edge to edge)', hh, RULES['hole_hole'])
    he = min(float(edge_d[at(x, y)]) - dia / 2 for (x, y, dia) in holes)
    rule('hole edge to board edge', he, RULES['hole_edge'])
    for key in ('F_Cu', 'B_Cu'):
        m = img[key] & inside
        rule(f'{key} copper to board edge', float(edge_d[m].min()), RULES['cu_edge'])
        rule(f'{key} copper outside outline (px)', float((img[key] & ~inside).sum()), 0.0, ok=not (img[key] & ~inside).any())

    # ---- solder mask bridges: openings closer than 0.2 mm merge under a closing
    for key in ('F_Mask', 'B_Mask'):
        op = img[key]
        closed = ndimage.binary_closing(op, structure=disk(RULES['mask_bridge'] / 2))
        bridges = closed & ~op
        lab_b, nb = ndimage.label(bridges)
        # a genuine bridge violation is a blob of "closed" mask that touches two different openings
        bad = 0
        lab_o, no = ndimage.label(op)
        for b in range(1, nb + 1):
            blob = lab_b == b
            if blob.sum() < 4: continue
            touch = set(np.unique(lab_o[ndimage.binary_dilation(blob)])) - {0}
            if len(touch) >= 2: bad += 1
        rule(f'{key} mask bridges < 0.20 mm (count)', float(bad), 0.0, ok=bad == 0)

    # ---- silkscreen
    for key, mkey in (('F_Silkscreen', 'F_Mask'), ('B_Silkscreen', 'B_Mask')):
        aps, items = aps_all[key]
        ws = [aps[it[1]][1][0] for it in items if it[0] == 'line']
        rule(f'{key} min line aperture', min(ws), RULES['silk_w'])
        thin = min_feature(img[key], RULES['silk_w'])
        rule(f'{key} features thinner than 0.153 (area)', thin, 0.0, ok=thin == 0.0)
        ov = float((img[key] & img[mkey]).sum()) * RES * RES
        rule(f'{key} over mask openings (area)', ov, 0.0, ok=ov == 0.0)
        s = img[key] & inside
        rule(f'{key} to board edge', float(edge_d[s].min()) if s.any() else 99, RULES['silk_edge'])
        rule(f'{key} outside outline (px)', float((img[key] & ~inside).sum()), 0.0, ok=not (img[key] & ~inside).any())

    print(f'[{variant}] JLCPCB 2-layer DRC on {name} ({R.W}x{R.H} px at {RES} mm)')
    for r in report: print(r)
    print(f'[{variant}] DRC RESULT: {"PASS" if not errors else "FAIL - " + ", ".join(errors)}')
    return errors

if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else 'U'
    drc(v)
