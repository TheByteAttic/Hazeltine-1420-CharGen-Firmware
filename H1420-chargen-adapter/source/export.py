# Copyright (c) 2026 by The Byte Attic B.V.
"""Gerber (RS-274X), Excellon drill, and KiCad .kicad_pcb export from layout_<variant>.json."""
import json, math, os, sys, zipfile
import numpy as np
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties
from design import PARTS, part_pose, NETS

SILK_W = 0.16          # JLCPCB: silkscreen line width >= 0.153 mm
TEXT_W = 0.16          # outline stroke added around filled glyphs
MASK_EXP = 0.05
SILK_PAD_CLEAR = 0.15  # silkscreen to solder-mask opening
FONT = FontProperties(family='DejaVu Sans', weight='bold')

# ----------------------------------------------------------------- text as filled glyphs
def _glyph(ch, h):
    tp = TextPath((0, 0), ch, size=h * 1.4, prop=FONT)
    polys = [[tuple(p) for p in q] for q in tp.to_polygons() if len(q) >= 3]
    return polys

def _contains(outer, pt):
    x, y = pt; inside = False
    for (x1, y1), (x2, y2) in zip(outer, outer[1:] + outer[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside

def text_glyphs(s, x, y, h=1.0, mirror=False, rot=0, tracking=0.12):
    """Text s centred at (x, y), cap height ~h, as a list of glyphs; each glyph is
    (outer_polygon, [hole_polygons]).  Characters are laid out one by one with extra
    tracking so neighbouring letters keep a printable gap."""
    glyphs = []; cursor = 0.0
    for ch in s:
        if ch == ' ':
            cursor += 0.45 * h; continue
        polys = _glyph(ch, h)
        xs = [p[0] for q in polys for p in q]
        if not xs:
            continue
        x0, x1 = min(xs), max(xs)
        shifted = [[(px - x0 + cursor, py) for (px, py) in q] for q in polys]
        # classify contours: a contour inside another one of the same glyph is a hole
        outers, holes = [], {}
        for i, q in enumerate(shifted):
            parents = [j for j, r in enumerate(shifted) if j != i and _contains(r, q[0])]
            if len(parents) % 2 == 1:
                holes.setdefault(max(parents, key=lambda j: -len(shifted[j])), []).append(q)
            else:
                outers.append(i)
        for i in outers:
            glyphs.append((shifted[i], holes.get(i, [])))
        cursor += (x1 - x0) + tracking
    if not glyphs:
        return []
    xs = [p[0] for g in glyphs for p in g[0]]; ys = [p[1] for g in glyphs for p in g[0]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    a = math.radians(rot)
    def tf(q):
        out = []
        for (px, py) in q:
            px, py = px - cx, py - cy
            if mirror:
                px = -px
            out.append((x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a)))
        return out
    return [(tf(o), [tf(hh) for hh in hs]) for (o, hs) in glyphs]

def text_strokes(s, x, y, h=1.0, mirror=False, rot=0):
    """Outline polylines of the text (kept for callers that only need the outline)."""
    out = []
    for o, hs in text_glyphs(s, x, y, h, mirror, rot):
        out.append(o + [o[0]])
        for hh in hs:
            out.append(hh + [hh[0]])
    return out

def _bbox(pts, grow=0.0):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow)

def _boxes_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

# ----------------------------------------------------------------- silkscreen content
class SilkPlacer:
    """Collision-aware placement of silkscreen text: a label must not touch a solder-mask
    opening (pads, both sides for through-hole), another part's body outline, another
    label, or the board edge on its layer."""
    def __init__(self, d):
        from board import point_in_poly
        self.pip = point_in_poly
        self.outline = d['outline']
        self.keep = {'top': [], 'bot': []}       # (bbox, tag)
        for p in d['pads']:
            if p['shape'] == 'smd':
                hw, hh = p['size'][0] / 2, p['size'][1] / 2; layers = p['layers']
            else:
                hw = hh = p['size'] / 2; layers = ('top', 'bot')
            g = MASK_EXP + SILK_PAD_CLEAR
            for L in layers:
                self.keep[L].append(((p['x'] - hw - g, p['y'] - hh - g, p['x'] + hw + g, p['y'] + hh + g), 'pad:' + p['ref']))
        for vv in d['vias']:
            r = vv.get('d', 0.6) / 2 + SILK_PAD_CLEAR
            for L in ('top', 'bot'):
                self.keep[L].append(((vv['x'] - r, vv['y'] - r, vv['x'] + r, vv['y'] + r), 'via'))
        self.texts = {'top': [], 'bot': []}
        self.warnings = []
    def add_lines(self, layer, pl, w, tag):
        for (x1, y1), (x2, y2) in zip(pl, pl[1:]):
            self.keep[layer].append(((min(x1, x2) - w / 2, min(y1, y2) - w / 2, max(x1, x2) + w / 2, max(y1, y2) + w / 2), tag))
    def add_body(self, layer, box, ref):
        self.keep[layer].append((box, 'body:' + ref))
    def inside(self, box, margin=0.35):
        x0, y0, x1, y1 = box
        for (x, y) in ((x0 - margin, y0 - margin), (x1 + margin, y0 - margin), (x1 + margin, y1 + margin), (x0 - margin, y1 + margin),
                       ((x0 + x1) / 2, y0 - margin), ((x0 + x1) / 2, y1 + margin)):
            if not self.pip(x, y, self.outline):
                return False
        return True
    def conflicts(self, layer, box, own=None):
        out = []
        for b, tag in self.keep[layer]:
            if tag == 'body:' + str(own):
                continue
            if _boxes_overlap(box, b):
                out.append(tag)
        for b, tag in self.texts[layer]:
            if _boxes_overlap(box, b):
                out.append('text:' + tag)
        if not self.inside(box):
            out.append('edge')
        return out
    def place(self, layer, s, candidates, h, mirror, own=None, gap=0.12, strict=False):
        """candidates: list of (x, y, rot).  Returns glyphs of the first collision-free
        candidate (or the least-conflicting one, with a warning)."""
        best = None
        for (x, y, rot) in candidates:
            gl = text_glyphs(s, x, y, h, mirror, rot)
            box = _bbox([p for g in gl for p in g[0]], TEXT_W / 2 + gap)
            c = self.conflicts(layer, box, own)
            hard = [t for t in c if t != 'via']          # silk over a tented via is tolerated, but avoided when possible
            score = 100 * len(hard) + len(c)
            if score == 0:
                best = (0, gl, box, c, hard); break
            if best is None or score < best[0]:
                best = (score, gl, box, c, hard)
        n, gl, box, c, hard = best
        if hard and strict:
            return None
        if hard:
            self.warnings.append(f'{layer} "{s}": no clean position, conflicts {hard}')
        self.texts[layer].append((box, s))
        return gl

def _seg_rect_interval(p, q, r):
    """Parameter interval [t0, t1] of segment p->q inside axis-aligned rect r, or None."""
    (x1, y1), (x2, y2) = p, q
    t0, t1 = 0.0, 1.0
    for (pp, qq) in ((-(x2 - x1), x1 - r[0]), (x2 - x1, r[2] - x1), (-(y2 - y1), y1 - r[1]), (y2 - y1, r[3] - y1)):
        if abs(pp) < 1e-12:
            if qq < 0: return None
            continue
        t = qq / pp
        if pp < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1: return None
    return (t0, t1)

def clip_polyline(pl, rects, min_len=0.25):
    """Remove the parts of polyline pl that fall inside any of the rects."""
    out = []; cur = []
    for p, q in zip(pl, pl[1:]):
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        if L < 1e-9: continue
        ivals = sorted(i for i in (_seg_rect_interval(p, q, r) for r in rects) if i)
        merged = []
        for a, b in ivals:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        t = 0.0
        pieces = []
        for a, b in merged:
            if a > t: pieces.append((t, a))
            t = max(t, b)
        if t < 1.0: pieces.append((t, 1.0))
        for a, b in pieces:
            pa = (p[0] + (q[0] - p[0]) * a, p[1] + (q[1] - p[1]) * a)
            pb = (p[0] + (q[0] - p[0]) * b, p[1] + (q[1] - p[1]) * b)
            if cur and abs(cur[-1][0] - pa[0]) < 1e-9 and abs(cur[-1][1] - pa[1]) < 1e-9:
                cur.append(pb)
            else:
                if len(cur) > 1: out.append(cur)
                cur = [pa, pb]
    if len(cur) > 1: out.append(cur)
    # drop slivers
    keep = []
    for c in out:
        if sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(c, c[1:])) >= min_len:
            keep.append(c)
    return keep

def place_beside(sp, layer, s, ref, x, y, w, h, mirror, v):
    """Label a passive: candidates are the four sides of the body (label parallel to the
    body's long axis first), at 1.0 mm then 0.8 mm cap height, then a ring of nearby spots."""
    for lab_h in (1.0, 0.8):
        gl = text_glyphs(s, 0, 0, lab_h)
        bx = _bbox([p for g in gl for p in g[0]])
        tw, th = bx[2] - bx[0], bx[3] - bx[1]
        o = 0.5 + TEXT_W
        below = (x, y - h / 2 - o - th / 2, 0); above = (x, y + h / 2 + o + th / 2, 0)
        left = (x - w / 2 - o - tw / 2, y, 0); right = (x + w / 2 + o + tw / 2, y, 0)
        rleft = (x - w / 2 - o - th / 2, y, 90); rright = (x + w / 2 + o + th / 2, y, 90)
        rbelow = (x, y - h / 2 - o - tw / 2, 90); rabove = (x, y + h / 2 + o + tw / 2, 90)
        if w >= h:
            cands = [below, above, left, right, rleft, rright, rbelow, rabove]
        else:
            cands = [rleft, rright, below, above, left, right, rbelow, rabove]
        if v == 'L':
            cands[0], cands[1] = cands[1], cands[0]
        ring = []
        for r in (2.2, 2.8, 3.4, 4.0):
            for k in range(12):
                a = 2 * math.pi * k / 12
                ring.append((x + r * math.cos(a), y + r * math.sin(a), 0))
        cands += ring
        gl = sp.place(layer, s, cands, lab_h, mirror, own=ref, strict=True)
        if gl is not None:
            return gl
    return sp.place(layer, s, cands, 0.8, mirror, own=ref)

def silk_items(d):
    """Return {'top': [item], 'bot': [item]} with item = ('line', polyline, width) or
    ('fill', outer, holes, stroke_width)."""
    if '_silk_items' in d:
        return d['_silk_items']
    v = d['variant']
    items = {'top': [], 'bot': []}
    sp = SilkPlacer(d)
    def add(layer, pl, w=SILK_W):
        items[layer].append(('line', pl, w))
    def add_text(layer, glyphs):
        for o, hs in glyphs:
            items[layer].append(('fill', o, hs, TEXT_W))
    # bodies first (keep-outs for labels)
    bodies = {}
    for ref, p in PARTS.items():
        x, y, rot = part_pose(ref, v)
        w, h = p['body']
        if rot % 180 == 90:
            w, h = h, w
        bodies[ref] = (x, y, w, h, rot)
        if ref != 'P1':
            sp.add_body(p['side'], (x - w / 2, y - h / 2, x + w / 2, y + h / 2), ref)
    for ref, p in PARTS.items():
        x, y, w, h, rot = bodies[ref]
        side = p['side']
        if ref == 'P1':
            add('top', [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2), (x - w / 2, y - h / 2)])
            add('top', [(x - w / 2, y - 1.5), (x - w / 2 + 1.0, y), (x - w / 2, y + 1.5)])
            sp.add_lines('top', [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2), (x - w / 2, y - h / 2)], SILK_W, 'outline:P1')
            sp.keep['top'].append(((x - w / 2 - 0.2, y - 1.7, x - w / 2 + 1.2, y + 1.7), 'notch:P1'))
            add_text('top', sp.place('top', '1', [(x - w / 2 - 1.6, y - 3.81, 0), (x - w / 2 - 1.6, y + 3.81, 0)], 1.0, False))
            continue
        layer = side
        mirror = (side == 'bot')
        add(layer, [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2), (x - w / 2, y - h / 2)])
        pads = [t for t in d['pads'] if t['ref'] == ref]
        p1 = next((t for t in pads if t['pin'] in (1, 'A')), None)
        passive = ref[0] in 'RC'
        if p1 and not passive and not ref.startswith('JP'):
            dx = -1 if p1['x'] < x else 1
            if ref == 'U5':
                mx, my = p1['x'] + dx * 1.9, p1['y']
            else:
                mx, my = p1['x'] + dx * (p1['size'][0] / 2 + 0.55 if p1['shape'] == 'smd' else 1.6), p1['y']
            circle = [(mx + 0.25 * math.cos(t), my + 0.25 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 13)]
            add(layer, circle, 0.3)
            sp.texts[layer].append(((mx - 0.5, my - 0.5, mx + 0.5, my + 0.5), 'dot:' + ref))
        if passive:
            add_text(layer, place_beside(sp, layer, ref, ref, x, y, w, h, mirror, v))
        elif ref in ('JP1', 'JP2'):
            # fixed scheme in the neck: the two chip labels sit beside their pads on one side of the
            # jumper, the reference on the other side; JP1 (rotated) uses the opposite bands from JP2
            pa = next(t for t in pads if t['pin'] == 'A'); pb = next(t for t in pads if t['pin'] == 'B')
            sgn = 1 if pa['x'] < pb['x'] else -1
            add_text(layer, sp.place(layer, ref, [(pa['x'] + sgn * 0.1, y + sgn * 1.85, 0)], 0.85, mirror, own=ref))
            add_text(layer, sp.place(layer, '8678', [(pa['x'] + sgn * 0.2, pa['y'] - sgn * 1.55, 0)], 0.7, mirror, own=ref))
            add_text(layer, sp.place(layer, '86S64', [(pb['x'] + sgn * 0.8, pb['y'] + sgn * 1.55, 0)], 0.7, mirror, own=ref))
        else:
            add_text(layer, sp.place(layer, ref, [(x, y, 0)], 1.0 if ref != 'U5' else 1.2, mirror, own=ref))
    # board legend and notices (top)
    legend = 'HAZELTINE 1420 CHARGEN ADAPTER - ' + ('U26 UPPER' if v == 'U' else 'U25 LOWER')
    ly = 1.7 if v == 'U' else 12.3
    add_text('top', sp.place('top', legend, [(xx, ly + dy, 0) for dy in (0, -0.2, 0.2, -0.4, 0.4) for xx in (25.0, 24.0, 26.0, 23.0, 27.0)], 0.8, False, gap=0.2))
    add_text('top', sp.place('top', 'PIN 1 = SOCKET NOTCH END', [(xx, yy, 0) for yy in (1.3, 12.7, 1.1, 12.9) for xx in (61.5, 62.5, 60.5, 63.5)], 0.7, False, gap=0.2))
    cy_ = 22.0 if v == 'U' else 2 * 6.985 - 22.0
    add_text('top', sp.place('top', 'Copyright (c) 2026 by The Byte Attic B.V.',
                             [(xx, cy_, 0) for xx in (30.0, 14.0, 13.0, 15.0, 16.0, 20.0, 25.0, 34.0, 12.5)], 0.8, False, gap=0.2))
    # clip every silkscreen line against the solder-mask openings of its layer (pads + expansion + clearance)
    for L in ('top', 'bot'):
        rects = [b for (b, tag) in sp.keep[L] if tag.startswith('pad:')]
        clipped = []
        for it in items[L]:
            if it[0] != 'line':
                clipped.append(it); continue
            for pl in clip_polyline(it[1], rects):
                clipped.append(('line', pl, it[2]))
        items[L] = clipped
    for wmsg in sp.warnings:
        print('SILK WARNING:', wmsg)
    d['_silk_warnings'] = sp.warnings
    d['_silk_boxes'] = [(L, b, s) for L in ('top', 'bot') for (b, s) in sp.texts[L]]
    d['_silk_items'] = items
    return items

# ----------------------------------------------------------------- gerber writer
class Gerber:
    def __init__(self, fn, function, polarity='Positive'):
        self.f = open(fn, 'w')
        self.aps = {}
        self.body = []
        self.fn = fn
        self.function = function
    def ap(self, kind, *dims):
        key = (kind,) + tuple(round(x, 4) for x in dims)
        if key not in self.aps:
            self.aps[key] = 10 + len(self.aps)
        return self.aps[key]
    def fmt(self, v):
        return f'{int(round(v * 1e6)):d}'
    def line(self, pts, w):
        code = self.ap('C', w)
        self.body.append(f'D{code}*')
        x0, y0 = pts[0]
        self.body.append(f'X{self.fmt(x0)}Y{self.fmt(y0)}D02*')
        for (x, y) in pts[1:]:
            self.body.append(f'X{self.fmt(x)}Y{self.fmt(y)}D01*')
    def region(self, pts):
        self.body.append('G36*')
        x0, y0 = pts[0]
        self.body.append(f'X{self.fmt(x0)}Y{self.fmt(y0)}D02*')
        for (x, y) in pts[1:] + [pts[0]]:
            self.body.append(f'X{self.fmt(x)}Y{self.fmt(y)}D01*')
        self.body.append('G37*')
    def flash(self, x, y, kind, *dims):
        code = self.ap(kind, *dims)
        self.body.append(f'D{code}*')
        self.body.append(f'X{self.fmt(x)}Y{self.fmt(y)}D03*')
    def close(self):
        f = self.f
        f.write('%TF.GenerationSoftware,cgadapter,export.py,1.0*%\n')
        f.write(f'%TF.FileFunction,{self.function}*%\n')
        f.write('%TF.FilePolarity,Positive*%\n' if 'Profile' not in self.function else '')
        f.write('%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\n')
        for key, code in self.aps.items():
            if key[0] == 'C':
                f.write(f'%ADD{code}C,{key[1]:.4f}*%\n')
            elif key[0] == 'R':
                f.write(f'%ADD{code}R,{key[1]:.4f}X{key[2]:.4f}*%\n')
            elif key[0] == 'O':
                f.write(f'%ADD{code}O,{key[1]:.4f}X{key[2]:.4f}*%\n')
        f.write('G01*\n')
        f.write('\n'.join(self.body) + '\n')
        f.write('M02*\n')
        f.close()

def write_gerbers(d, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    layers = {
        'F_Cu': Gerber(f'{outdir}/{name}-F_Cu.gbr', 'Copper,L1,Top'),
        'B_Cu': Gerber(f'{outdir}/{name}-B_Cu.gbr', 'Copper,L2,Bot'),
        'F_Mask': Gerber(f'{outdir}/{name}-F_Mask.gbr', 'Soldermask,Top'),
        'B_Mask': Gerber(f'{outdir}/{name}-B_Mask.gbr', 'Soldermask,Bot'),
        'F_SilkS': Gerber(f'{outdir}/{name}-F_Silkscreen.gbr', 'Legend,Top'),
        'B_SilkS': Gerber(f'{outdir}/{name}-B_Silkscreen.gbr', 'Legend,Bot'),
        'Edge': Gerber(f'{outdir}/{name}-Edge_Cuts.gbr', 'Profile,NP'),
    }
    cu = {'top': layers['F_Cu'], 'bot': layers['B_Cu']}
    mask = {'top': layers['F_Mask'], 'bot': layers['B_Mask']}
    for t in d['tracks']:
        cu[t['layer']].line(t['pts'], t['w'])
    for v in d['vias']:
        for L in ('top', 'bot'):
            cu[L].flash(v['x'], v['y'], 'C', 0.6)
        # vias tented: no mask opening
    for p in d['pads']:
        for L in p['layers']:
            if p['shape'] == 'smd':
                w, h = p['size']
                cu[L].flash(p['x'], p['y'], 'R', w, h)
                mask[L].flash(p['x'], p['y'], 'R', w + 2 * MASK_EXP, h + 2 * MASK_EXP)
            elif p['shape'] == 'rect':
                s = p['size']
                cu[L].flash(p['x'], p['y'], 'R', s, s)
                mask[L].flash(p['x'], p['y'], 'R', s + 2 * MASK_EXP, s + 2 * MASK_EXP)
            else:
                s = p['size']
                cu[L].flash(p['x'], p['y'], 'C', s)
                mask[L].flash(p['x'], p['y'], 'C', s + 2 * MASK_EXP)
    # teardrops (filled regions)
    for td in d.get('teardrops', []):
        cu[td['layer']].region([tuple(p) for p in td['pts']])
    # copper pours as polygon regions, written FIRST in the file (outer loops dark, holes clear)
    for layer, pr in d.get('pours', {}).items():
        g = cu[layer]
        head = []
        def region_lines(pts):
            out = ['G36*', f'X{g.fmt(pts[0][0])}Y{g.fmt(pts[0][1])}D02*']
            out += [f'X{g.fmt(x)}Y{g.fmt(y)}D01*' for (x, y) in pts[1:] + [pts[0]]]
            out.append('G37*')
            return out
        head.append('%LPD*%')
        for poly in pr['outers']:
            head += region_lines(poly)
        if pr['holes']:
            head.append('%LPC*%')
            for poly in pr['holes']:
                head += region_lines(poly)
            head.append('%LPD*%')
        g.body = head + g.body
    # silkscreen
    items = silk_items(d)
    for L, g in (('top', layers['F_SilkS']), ('bot', layers['B_SilkS'])):
        for it in items[L]:
            if it[0] == 'line':
                g.line(it[1], it[2])
            else:                       # filled glyph: region + outline stroke, holes cleared
                _, outer, holes, w = it
                g.region(outer)
                g.line(outer + [outer[0]], w)
                for hh in holes:
                    g.body.append('%LPC*%'); g.region(hh); g.body.append('%LPD*%')
                    g.line(hh + [hh[0]], w)
    # outline
    poly = d['outline'] + [d['outline'][0]]
    layers['Edge'].line(poly, 0.1)
    for g in layers.values():
        g.close()
    # drill (Excellon, plated)
    drills = {}
    for p in d['pads']:
        if p['shape'] != 'smd':
            drills.setdefault(round(p['hole'], 2), []).append((p['x'], p['y']))
    for v in d['vias']:
        drills.setdefault(0.3, []).append((v['x'], v['y']))
    with open(f'{outdir}/{name}-PTH.drl', 'w') as f:
        f.write('M48\n; DRILL file {cgadapter export.py} - Copyright (c) 2026 by The Byte Attic B.V.\n; FORMAT={-:-/ absolute / metric / decimal}\n')
        f.write('; #@! TF.FileFunction,Plated,1,2,PTH\nFMAT,2\nMETRIC\n')
        tools = sorted(drills)
        for i, dia in enumerate(tools):
            f.write(f'T{i+1}C{dia:.3f}\n')
        f.write('%\nG90\nG05\n')
        for i, dia in enumerate(tools):
            f.write(f'T{i+1}\n')
            for (x, y) in drills[dia]:
                f.write(f'X{x:.4f}Y{y:.4f}\n')
        f.write('T0\nM30\n')
    return layers

# ----------------------------------------------------------------- KiCad export
def kicad_pcb(d, fn):
    """Minimal KiCad 8 board file: footprints with pads, tracks, vias, outline, silkscreen."""
    v = d['variant']
    netnames = [''] + sorted(NETS.keys())
    nid = {n: i for i, n in enumerate(netnames)}
    K = lambda y: -y          # KiCad y axis points down
    out = ['(kicad_pcb (version 20240108) (generator "cgadapter") (generator_version "8.0")',
           '  (general (thickness 1.6) (legacy_teardrops no))',
           '  (paper "A4")',
           '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (34 "B.Paste" user) (35 "F.Paste" user)',
           '   (36 "B.SilkS" user "B.Silkscreen") (37 "F.SilkS" user "F.Silkscreen") (38 "B.Mask" user) (39 "F.Mask" user)',
           '   (44 "Edge.Cuts" user) (46 "B.CrtYd" user "B.Courtyard") (47 "F.CrtYd" user "F.Courtyard") (48 "B.Fab" user) (49 "F.Fab" user))',
           '  (setup (pad_to_mask_clearance 0.05) (pcbplotparams (layerselection 0x00010fc_ffffffff) (plot_on_all_layers_selection 0x0000000_00000000)))']
    for i, n in enumerate(netnames):
        out.append(f'  (net {i} "{n}")')
    # footprints
    pads_by_ref = {}
    for p in d['pads']:
        pads_by_ref.setdefault(p['ref'], []).append(p)
    for ref, plist in pads_by_ref.items():
        part = PARTS[ref]
        x, y, rot = part_pose(ref, v)
        layer = 'F.Cu' if part['side'] == 'top' else 'B.Cu'
        out.append(f'  (footprint "cgadapter:{ref}" (layer "{layer}") (at {x:.4f} {K(y):.4f})')
        out.append(f'    (property "Reference" "{ref}" (at 0 0) (layer "{"F.SilkS" if part["side"] == "top" else "B.SilkS"}") (effects (font (size 0.8 0.8) (thickness 0.12)) {"(justify mirror)" if part["side"] == "bot" else ""}))')
        out.append(f'    (property "Value" "{part["value"]}" (at 0 0) (layer "{"F.Fab" if part["side"] == "top" else "B.Fab"}") hide (effects (font (size 0.8 0.8) (thickness 0.12))))')
        for p in plist:
            dx, dy = p['x'] - x, -(p['y'] - y)
            net = p['net']
            nets = f'(net {nid[net]} "{net}")' if net else ''
            if p['shape'] == 'smd':
                w, h = p['size']
                lay = '"F.Cu" "F.Paste" "F.Mask"' if part['side'] == 'top' else '"B.Cu" "B.Paste" "B.Mask"'
                out.append(f'    (pad "{p["pin"]}" smd rect (at {dx:.4f} {dy:.4f}) (size {w} {h}) (layers {lay}) {nets})')
            else:
                shp = 'rect' if p['shape'] == 'rect' else 'circle'
                out.append(f'    (pad "{p["pin"]}" thru_hole {shp} (at {dx:.4f} {dy:.4f}) (size {p["size"]} {p["size"]}) (drill {p["hole"]}) (layers "*.Cu" "*.Mask") {nets})')
        out.append('  )')
    # tracks / vias
    for t in d['tracks']:
        L = 'F.Cu' if t['layer'] == 'top' else 'B.Cu'
        for (x1, y1), (x2, y2) in zip(t['pts'], t['pts'][1:]):
            out.append(f'  (segment (start {x1:.4f} {K(y1):.4f}) (end {x2:.4f} {K(y2):.4f}) (width {t["w"]}) (layer "{L}") (net {nid[t["net"]]}))')
    for vv in d['vias']:
        out.append(f'  (via (at {vv["x"]:.4f} {K(vv["y"]):.4f}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net {nid[vv["net"]]}))')
    # outline
    poly = d['outline']
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        out.append(f'  (gr_line (start {x1:.4f} {K(y1):.4f}) (end {x2:.4f} {K(y2):.4f}) (layer "Edge.Cuts") (stroke (width 0.1) (type solid)))')
    for td in d.get('teardrops', []):
        L = 'F.Cu' if td['layer'] == 'top' else 'B.Cu'
        pts = ' '.join(f'(xy {x:.4f} {K(y):.4f})' for (x, y) in td['pts'])
        out.append(f'  (gr_poly (pts {pts}) (layer "{L}") (width 0) (fill solid))')
    # pours as zones (KiCad refills them itself: press B)
    for layer, pr in d.get('pours', {}).items():
        L = 'F.Cu' if layer == 'top' else 'B.Cu'
        pts = ' '.join(f'(xy {x:.4f} {K(y):.4f})' for (x, y) in poly)
        out.append(f'  (zone (net {nid[pr["net"]]}) (net_name "{pr["net"]}") (layer "{L}") (hatch edge 0.5) (connect_pads (clearance 0.3))'
                   f' (min_thickness 0.35) (filled_areas_thickness no) (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts {pts})))')
    # silkscreen strokes
    items = silk_items(d)
    for Lname, L in (('top', 'F.SilkS'), ('bot', 'B.SilkS')):
        for it in items[Lname]:
            if it[0] == 'line':
                pl, w = it[1], it[2]
                for (x1, y1), (x2, y2) in zip(pl, pl[1:]):
                    out.append(f'  (gr_line (start {x1:.4f} {K(y1):.4f}) (end {x2:.4f} {K(y2):.4f}) (layer "{L}") (stroke (width {w}) (type solid)))')
            else:
                _, outer, holes, w = it
                pts = ' '.join(f'(xy {x:.4f} {K(y):.4f})' for (x, y) in outer)
                out.append(f'  (gr_poly (pts {pts}) (layer "{L}") (stroke (width {w}) (type solid)) (fill none))')
                for hh in holes:
                    pts = ' '.join(f'(xy {x:.4f} {K(y):.4f})' for (x, y) in hh)
                    out.append(f'  (gr_poly (pts {pts}) (layer "{L}") (stroke (width {w}) (type solid)) (fill none))')
    out.append('  (gr_text "Copyright (c) 2026 by The Byte Attic B.V." (at 30 -25) (layer "Cmts.User") (effects (font (size 1 1) (thickness 0.15))))' if v == 'U' else
               '  (gr_text "Copyright (c) 2026 by The Byte Attic B.V." (at 30 12.5) (layer "Cmts.User") (effects (font (size 1 1) (thickness 0.15))))')
    out.append(')')
    open(fn, 'w').write('\n'.join(out))

if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else 'U'
    d = json.load(open(f'layout_{v}.json'))
    name = f'h1420-chargen-{"U26-upper" if v == "U" else "U25-lower"}'
    outdir = f'gerber_{v}'
    write_gerbers(d, outdir, name)
    kicad_pcb(d, f'{name}.kicad_pcb')
    with zipfile.ZipFile(f'{name}-gerbers.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(outdir)):
            z.write(f'{outdir}/{fn}', fn)
    print('wrote', outdir, name)
