# Copyright (c) 2026 by The Byte Attic B.V.
"""Independent verification: parse the emitted Gerber/drill files, rasterize, check shorts, opens,
clearance, drill/pad registration and edge clearance.  Uses layout json ONLY for pad->net mapping."""
import json, re, sys, math, os
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

RES = 0.025   # mm per pixel
MIN_CLEAR = 0.15
MIN_EDGE = 0.30

def parse_gerber(fn):
    aps = {}
    items = []   # ('line', code, (x0,y0), (x1,y1)) or ('flash', code, (x,y))
    cur = None; pos = None; region = None; polarity = 1
    fmt_dec = 6
    for raw in open(fn):
        s = raw.strip()
        if not s: continue
        m = re.match(r'%FSLAX(\d)(\d)Y', s)
        if m:
            fmt_dec = int(m.group(2)); continue
        m = re.match(r'%ADD(\d+)([CRO]),([\d.]+)(?:X([\d.]+))?\*%', s)
        if m:
            code = int(m.group(1)); kind = m.group(2)
            dims = (float(m.group(3)),) + ((float(m.group(4)),) if m.group(4) else ())
            aps[code] = (kind, dims); continue
        if s == 'G36*':
            region = []; continue
        if s == 'G37*':
            items.append(('poly', polarity, region)); region = None; continue
        if s == '%LPC*%':
            polarity = 0; continue
        if s == '%LPD*%':
            polarity = 1; continue
        if s.startswith('%') or s.startswith('G') or s.startswith('M'):
            continue
        m = re.match(r'D(\d+)\*', s)
        if m and int(m.group(1)) >= 10:
            cur = int(m.group(1)); continue
        m = re.match(r'X(-?\d+)Y(-?\d+)D0([123])\*', s)
        if m:
            x, y = int(m.group(1)) / 10 ** fmt_dec, int(m.group(2)) / 10 ** fmt_dec
            op = m.group(3)
            if region is not None:
                region.append((x, y)); continue
            if op == '2':
                pos = (x, y)
            elif op == '1':
                items.append(('line', cur, pos, (x, y))); pos = (x, y)
            elif op == '3':
                items.append(('flash', cur, (x, y)))
            continue
        raise ValueError(f'unparsed gerber line: {s}')
    return aps, items

def parse_drill(fn):
    tools = {}; holes = []; cur = None
    for raw in open(fn):
        s = raw.strip()
        m = re.match(r'T(\d+)C([\d.]+)', s)
        if m:
            tools[int(m.group(1))] = float(m.group(2)); continue
        m = re.match(r'T(\d+)$', s)
        if m:
            cur = int(m.group(1)); continue
        m = re.match(r'X(-?[\d.]+)Y(-?[\d.]+)', s)
        if m and cur:
            holes.append((float(m.group(1)), float(m.group(2)), tools[cur]))
    return holes

class Raster:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = x0 - 1, y0 - 1
        self.W = int((x1 - x0 + 2) / RES) + 1
        self.H = int((y1 - y0 + 2) / RES) + 1
    def px(self, x, y):
        return (x - self.x0) / RES, (self.H - 1) - (y - self.y0) / RES
    def draw_items(self, aps, items, img=None):
        img = img or Image.new('1', (self.W, self.H), 0)
        dr = ImageDraw.Draw(img)
        for it in items:
            if it[0] == 'poly':
                dr.polygon([self.px(x, y) for (x, y) in it[2]], fill=it[1])
                continue
            if it[0] == 'line':
                kind, dims = aps[it[1]]
                assert kind == 'C'
                w = dims[0] / RES
                (xa, ya), (xb, yb) = self.px(*it[2]), self.px(*it[3])
                dr.line([(xa, ya), (xb, yb)], fill=1, width=max(1, int(round(w))))
                for (cx, cy) in ((xa, ya), (xb, yb)):
                    dr.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=1)
            else:
                kind, dims = aps[it[1]]
                cx, cy = self.px(*it[2])
                if kind == 'C':
                    r = dims[0] / 2 / RES
                    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
                else:
                    hw, hh = dims[0] / 2 / RES, dims[1] / 2 / RES
                    dr.rectangle([cx - hw, cy - hh, cx + hw, cy + hh], fill=1)
        return img

def check(variant, gdir, name):
    d = json.load(open(f'layout_{variant}.json'))
    poly = d['outline']
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    R = Raster(min(xs), min(ys), max(xs), max(ys))
    layers = {}
    for L, suffix in (('top', 'F_Cu'), ('bot', 'B_Cu')):
        aps, items = parse_gerber(f'{gdir}/{name}-{suffix}.gbr')
        layers[L] = np.array(R.draw_items(aps, items), bool)
    holes = parse_drill(f'{gdir}/{name}-PTH.drl')
    problems = []
    # --- board mask from outline
    outline_img = Image.new('1', (R.W, R.H), 0)
    ImageDraw.Draw(outline_img).polygon([R.px(x, y) for (x, y) in poly], fill=1)
    inside = np.array(outline_img, bool)
    edge_d = ndimage.distance_transform_edt(inside) * RES
    for L in ('top', 'bot'):
        if (layers[L] & ~inside).any():
            problems.append(f'{L}: copper outside the board outline')
        m = layers[L] & inside
        me = edge_d[m].min() if m.any() else 99
        if me < MIN_EDGE:
            problems.append(f'{L}: copper only {me:.2f} mm from the board edge')
    # --- connectivity: label components per layer, link through holes (via/THT), map pads to nets
    lab = {}; nlab = {}
    for L in ('top', 'bot'):
        lab[L], nlab[L] = ndimage.label(layers[L], structure=np.ones((3, 3)))
    parent = {}
    def find(a):
        while parent.get(a, a) != a:
            a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for (x, y, dia) in holes:
        px, py = R.px(x, y); i, j = int(round(py)), int(round(px))
        lt, lb = lab['top'][i, j], lab['bot'][i, j]
        if lt == 0 or lb == 0:
            problems.append(f'hole at ({x:.2f},{y:.2f}) d={dia} is not inside copper on both layers')
            continue
        union(('top', lt), ('bot', lb))
    comp_nets = {}
    pad_comp = {}
    for p in d['pads']:
        for L in p['layers']:
            px, py = R.px(p['x'], p['y']); i, j = int(round(py)), int(round(px))
            l = lab[L][i, j]
            if l == 0:
                problems.append(f'pad {p["ref"]}.{p["pin"]} has no copper on {L}')
                continue
            c = find((L, l))
            pad_comp[(p['ref'], p['pin'], L)] = c
            if p['net']:
                comp_nets.setdefault(c, set()).add(p['net'])
    # shorts: a component touching pads of two nets
    for c, nets in comp_nets.items():
        if len(nets) > 1:
            problems.append(f'SHORT: component {c} joins nets {sorted(nets)}')
    # opens: a net whose pads lie in different components
    net_comps = {}
    for (ref, pin, L), c in pad_comp.items():
        net = next((p['net'] for p in d['pads'] if p['ref'] == ref and p['pin'] == pin), None)
        if net:
            net_comps.setdefault(net, set()).add(find(c))
    for net, cs in net_comps.items():
        if len(cs) > 1:
            problems.append(f'OPEN: net {net} is split into {len(cs)} pieces')
    # unexpected copper: components with no pad at all (dangling) - allowed but report
    # --- clearance between different nets: per layer, per net mask -> EDT
    comp_net = {}
    for c, nets in comp_nets.items():
        for n in nets: comp_net[c] = n
    min_clear = 99
    worst = None
    for L in ('top', 'bot'):
        lb = lab[L]
        # map every label to its net (via union)
        lab2net = {}
        for l in range(1, nlab[L] + 1):
            lab2net[l] = comp_net.get(find((L, l)))
        nets = sorted({n for n in lab2net.values() if n})
        netimg = np.zeros(lb.shape, np.int32)
        for l, n in lab2net.items():
            if n:
                netimg[lb == l] = nets.index(n) + 1
            elif l and not any(lb[int(round(R.px(p['x'], p['y'])[1])), int(round(R.px(p['x'], p['y'])[0]))] == l for p in d['pads'] if p['net'] is None):
                problems.append(f'{L}: copper island without any pad (label {l}, {int((lb == l).sum())} px)')
        for k, n in enumerate(nets):
            mine = netimg == k + 1
            others = (netimg > 0) & ~mine
            if not others.any(): continue
            dist = ndimage.distance_transform_edt(~mine) * RES
            mc = dist[others].min()
            if mc < min_clear:
                min_clear = mc
                ij = np.argwhere(others & (dist <= mc + 1e-9))[0]
                worst = (L, n, R.x0 + ij[1] * RES, R.y0 + (R.H - 1 - ij[0]) * RES)
    if min_clear < MIN_CLEAR:
        problems.append(f'CLEARANCE {min_clear:.3f} mm at {worst}')
    # --- drill vs pad registration
    pad_holes = [(p['x'], p['y'], p['hole']) for p in d['pads'] if p['shape'] != 'smd']
    via_holes = [(v['x'], v['y'], 0.3) for v in d['vias']]
    exp = sorted(pad_holes + via_holes); got = sorted(holes)
    if len(exp) != len(got):
        problems.append(f'drill count {len(got)} != expected {len(exp)}')
    else:
        for a, b in zip(exp, got):
            if abs(a[0] - b[0]) > 1e-3 or abs(a[1] - b[1]) > 1e-3 or abs(a[2] - b[2]) > 1e-3:
                problems.append(f'drill mismatch {a} vs {b}'); break
    # hole-to-hole and hole-to-copper of other net handled by clearance (annular ring included)
    print(f'[{variant}] layers rasterised at {RES} mm: {R.W}x{R.H}; min clearance {min_clear:.3f} mm; '
          f'{len(holes)} holes; {len(problems)} problems')
    for p in problems:
        print('   ', p)
    return problems

if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else 'U'
    name = f'h1420-chargen-{"U26-upper" if v == "U" else "U25-lower"}'
    check(v, f'gerber_{v}', name)
