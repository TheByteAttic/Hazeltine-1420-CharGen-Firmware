# Copyright (c) 2026 by The Byte Attic B.V.
"""Post-route geometric cleanup:
  * trim track ends that overshoot inside pads (end exactly at the pad centre)
  * straighten: replace wiggly runs by the shortest octilinear (0/45/90 deg) 1- or 2-segment path
    whenever the result keeps clearance to every other net
  * chamfer remaining 90-degree corners into 45-degree ones
  * add teardrops where a track meets a via or a round through-hole pad
  * regenerate the GND pour
Every edit is checked geometrically against all other copper (clearance CL) and the outline.
"""
import json, math, sys
import numpy as np
from pour import make_pour, scanlines, mask_polygons, POUR_NETS

CL = 0.20          # track-to-track / via clearance kept by every edit
CL_PAD = 0.30      # track-to-pad clearance kept by every edit
EDGE = 0.32        # copper to board edge
GRID = 0.254

# ----------------------------------------------------------------- geometry helpers
def seg_seg_dist(a1, a2, b1, b2):
    """min distance between segments a and b (2D)."""
    def d_ps(p, s1, s2):
        x, y = p; x1, y1 = s1; x2, y2 = s2
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 == 0:
            return math.hypot(x - x1, y - y1)
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L2))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    # intersection test
    d1, d2 = cross(b1, b2, a1), cross(b1, b2, a2)
    d3, d4 = cross(a1, a2, b1), cross(a1, a2, b2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return 0.0
    return min(d_ps(a1, b1, b2), d_ps(a2, b1, b2), d_ps(b1, a1, a2), d_ps(b2, a1, a2))

def seg_rect_dist(a1, a2, cx, cy, hw, hh, n=24):
    best = 1e9
    for k in range(n + 1):
        t = k / n
        x, y = a1[0] + (a2[0] - a1[0]) * t, a1[1] + (a2[1] - a1[1]) * t
        best = min(best, math.hypot(max(abs(x - cx) - hw, 0), max(abs(y - cy) - hh, 0)))
    return best

def point_seg_dist(p, s1, s2):
    return seg_seg_dist(p, p, s1, s2)

class Copper:
    """Index of copper items for clearance queries.  item = (net, layer, kind, data, halfw)
       kind 'seg': data=(p1,p2); 'circ': data=(x,y,r); 'rect': data=(x,y,hw,hh)"""
    def __init__(self, outline):
        self.items = []
        self.grid = {}
        self.cell = 2.0
        self.outline = outline
    def _keys(self, bbox):
        x0, y0, x1, y1 = bbox
        for i in range(int(x0 // self.cell), int(x1 // self.cell) + 1):
            for j in range(int(y0 // self.cell), int(y1 // self.cell) + 1):
                yield (i, j)
    def add(self, net, layer, kind, data, halfw, tag=None):
        if kind == 'seg':
            (x1, y1), (x2, y2) = data
            bbox = (min(x1, x2) - halfw, min(y1, y2) - halfw, max(x1, x2) + halfw, max(y1, y2) + halfw)
        elif kind == 'circ':
            x, y, r = data; bbox = (x - r, y - r, x + r, y + r)
        else:
            x, y, hw, hh = data; bbox = (x - hw, y - hh, x + hw, y + hh)
        idx = len(self.items)
        self.items.append((net, layer, kind, data, halfw, tag, bbox))
        for k in self._keys(bbox):
            self.grid.setdefault(k, []).append(idx)
        return idx
    def remove(self, idx):
        self.items[idx] = None
    def clearance_seg(self, net, layer, p1, p2, halfw, ignore=()):
        """min clearance MARGIN of a segment of `net` on `layer` to other-net copper and the board
        edge: (distance - required clearance), so >= 0 means legal.  Pads require CL_PAD, tracks and
        vias CL."""
        bbox = (min(p1[0], p2[0]) - halfw - 1.0, min(p1[1], p2[1]) - halfw - 1.0,
                max(p1[0], p2[0]) + halfw + 1.0, max(p1[1], p2[1]) + halfw + 1.0)
        best = 1e9
        seen = set()
        for k in self._keys(bbox):
            for idx in self.grid.get(k, ()):
                if idx in seen: continue
                seen.add(idx)
                it = self.items[idx]
                if it is None or it[0] == net or it[1] != layer or idx in ignore: continue
                if it[5] is not None and it[5] in ignore: continue
                _, _, kind, data, hw2, _, bb = it
                if bb[0] > bbox[2] or bb[2] < bbox[0] or bb[1] > bbox[3] or bb[3] < bbox[1]: continue
                tag = it[5]
                req = CL_PAD if tag == 'pad' else CL
                if kind == 'seg':
                    d = seg_seg_dist(p1, p2, data[0], data[1]) - halfw - hw2
                elif kind == 'circ':
                    d = point_seg_dist((data[0], data[1]), p1, p2) - data[2] - halfw
                else:
                    d = seg_rect_dist(p1, p2, data[0], data[1], data[2], data[3]) - halfw
                best = min(best, d - req)
        # board edge
        n = len(self.outline)
        for i in range(n):
            e1, e2 = self.outline[i], self.outline[(i + 1) % n]
            best = min(best, seg_seg_dist(p1, p2, e1, e2) - halfw - EDGE)
        return best

def octilinear(a, b):
    """the two candidate 2-point octilinear paths from a to b (as lists of interior points)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) < 1e-9 or abs(dy) < 1e-9 or abs(abs(dx) - abs(dy)) < 1e-9:
        return [[]]                      # already a single octilinear segment
    d = min(abs(dx), abs(dy))
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    # diagonal first, then straight
    m1 = (a[0] + sx * d, a[1] + sy * d)
    # straight first, then diagonal
    m2 = (b[0] - sx * d, b[1] - sy * d)
    return [[m1], [m2]]

def is_octilinear(a, b):
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    return dx < 1e-6 or dy < 1e-6 or abs(dx - dy) < 1e-6

# ----------------------------------------------------------------- cleanup
class Cleaner:
    def __init__(self, d):
        self.d = d
        self.outline = d['outline']
        self.cu = Copper(self.outline)
        self.pads = d['pads']
        self.vias = d['vias']
        self.tracks = [dict(t) for t in d['tracks']]
        for t in self.tracks:
            t['pts'] = [tuple(p) for p in t['pts']]
        self.__init_static__()
        self.track_items = {}     # track index -> list of item indices
        for ti, t in enumerate(self.tracks):
            self.index_track(ti)
        self.teardrops = []

    def __init_static__(self):
        for p in self.pads:
            for L in p['layers']:
                if p['shape'] == 'smd':
                    self.cu.add(p['net'], L, 'rect', (p['x'], p['y'], p['size'][0] / 2, p['size'][1] / 2), 0, tag='pad')
                elif p['shape'] == 'rect':
                    self.cu.add(p['net'], L, 'rect', (p['x'], p['y'], p['size'] / 2, p['size'] / 2), 0, tag='pad')
                else:
                    self.cu.add(p['net'], L, 'circ', (p['x'], p['y'], p['size'] / 2), 0, tag='pad')
        for v in self.vias:
            for L in ('top', 'bot'):
                self.cu.add(v['net'], L, 'circ', (v['x'], v['y'], 0.3), 0, tag='via')

    def index_track(self, ti):
        t = self.tracks[ti]
        for idx in self.track_items.get(ti, []):
            self.cu.remove(idx)
        self.track_items[ti] = [self.cu.add(t['net'], t['layer'], 'seg', (a, b), t['w'] / 2, tag=('t', ti))
                                for a, b in zip(t['pts'], t['pts'][1:])]

    def path_ok(self, ti, pts):
        t = self.tracks[ti]
        ign = {('t', ti)}
        for a, b in zip(pts, pts[1:]):
            if self.cu.clearance_seg(t['net'], t['layer'], a, b, t['w'] / 2, ignore=ign) < 0:
                return False
        return True

    # --- 0b. merge pairs of same-net/same-layer tracks that meet end to end at a point that is not
    #         a pad, a via or a junction with a third track, so that corner clean-up sees one polyline
    def merge_degree2(self):
        fixed = {(round(p['x'], 3), round(p['y'], 3)) for p in self.pads} | {(round(v['x'], 3), round(v['y'], 3)) for v in self.vias}
        n = 0
        while True:
            ends = {}
            for ti, t in enumerate(self.tracks):
                if t.get('dead') or len(t['pts']) < 2: continue
                for end in (0, -1):
                    p = t['pts'][end]
                    ends.setdefault((t['net'], t['layer'], round(p[0], 3), round(p[1], 3)), []).append((ti, end))
            merged = False
            for key, lst in ends.items():
                if len(lst) != 2 or (key[2], key[3]) in fixed: continue
                (ta, ea), (tb, eb) = lst
                if ta == tb: continue
                A, B = self.tracks[ta], self.tracks[tb]
                if abs(A['w'] - B['w']) > 1e-9: continue
                pa = A['pts'] if ea == -1 else A['pts'][::-1]      # ends at the junction
                pb = B['pts'] if eb == 0 else B['pts'][::-1]       # starts at the junction
                A['pts'] = list(pa) + list(pb[1:])
                B['dead'] = True
                self.index_track(ta)
                for idx in self.track_items.get(tb, []): self.cu.remove(idx)
                self.track_items[tb] = []
                n += 1; merged = True
                break
            if not merged:
                break
        self.purge_dead()
        return n

    # --- 0. split tracks where other same-net tracks end on them (T-junctions must stay put)
    def split_at_junctions(self):
        # first snap track ends that lie on another track close to one of its vertices onto that vertex
        for ti, t in enumerate(self.tracks):
            for end in (0, 1):
                p = t['pts'][0] if end == 0 else t['pts'][-1]
                if self.anchor_at(t['net'], t['layer'], p) is not None: continue
                best = None
                for tj, o in enumerate(self.tracks):
                    if tj == ti or o['net'] != t['net'] or o['layer'] != t['layer']: continue
                    for a, b in zip(o['pts'], o['pts'][1:]):
                        if point_seg_dist(p, a, b) <= o['w'] / 2 + 1e-6:
                            for q in (a, b):
                                dd = math.hypot(p[0] - q[0], p[1] - q[1])
                                if 1e-6 < dd <= 0.4 and (best is None or dd < best[0]):
                                    best = (dd, q)
                if best:
                    q = best[1]
                    pts = list(t['pts'])
                    if end == 0: pts[0] = q
                    else: pts[-1] = q
                    if self.path_ok(ti, pts):
                        t['pts'] = self.dedupe(pts); self.index_track(ti)
        ends = [(t['net'], t['layer'], p) for t in self.tracks for p in (t['pts'][0], t['pts'][-1])]
        ends += [(v['net'], L, (v['x'], v['y'])) for v in self.vias for L in ('top', 'bot')]
        ends += [(p['net'], L, (p['x'], p['y'])) for p in self.pads for L in p['layers']]
        new_tracks = []
        nsplit = 0
        for t in self.tracks:
            pts = t['pts']
            cuts = []   # (segment index, point)
            for (net, layer, p) in ends:
                if net != t['net'] or layer != t['layer']: continue
                if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-6 for q in (pts[0], pts[-1])): continue
                for k, (a, b) in enumerate(zip(pts, pts[1:])):
                    if point_seg_dist(p, a, b) <= t['w'] / 2 + 1e-6:
                        cuts.append((k, p)); break
            if not cuts:
                new_tracks.append(t); continue
            # insert cut points as vertices and split
            pieces = []
            cur = [pts[0]]
            for k, (a, b) in enumerate(zip(pts, pts[1:])):
                here = sorted([p for (kk, p) in cuts if kk == k], key=lambda p: math.hypot(p[0] - a[0], p[1] - a[1]))
                for p in here:
                    if math.hypot(p[0] - cur[-1][0], p[1] - cur[-1][1]) > 1e-6:
                        cur.append(p)
                    pieces.append(cur); cur = [p]
                if math.hypot(b[0] - cur[-1][0], b[1] - cur[-1][1]) > 1e-6:
                    cur.append(b)
            pieces.append(cur)
            for pc in pieces:
                if len(pc) >= 2:
                    new_tracks.append(dict(net=t['net'], layer=t['layer'], pts=pc, w=t['w']))
            nsplit += len(pieces) - 1
        self.tracks = new_tracks
        self.track_items = {}
        self.cu = Copper(self.outline)
        self.__init_static__()
        for ti in range(len(self.tracks)):
            self.index_track(ti)
        return nsplit

    # --- 0b. trim dangling ends: a track end that is on no pad/via centre and on no other track is
    #         cut back to the last point where other same-net copper joins the track
    def trim_dangling(self):
        n = 0
        for ti, t in enumerate(self.tracks):
            for end in (0, 1):
                pts = t['pts'] if end == 0 else t['pts'][::-1]
                p0 = pts[0]
                if self.anchor_at(t['net'], t['layer'], p0) is not None: continue
                if self.on_other_track(ti, p0): continue
                # walk along the track from the dangling end and find the first junction
                joints = self.junction_points(ti)
                if not joints:
                    continue
                cut = None
                for k, (a, b) in enumerate(zip(pts, pts[1:])):
                    cand = [(math.hypot(q[0] - a[0], q[1] - a[1]), q) for q in joints if point_seg_dist(q, a, b) <= t['w'] / 2 + 1e-6]
                    if cand:
                        cut = (k, min(cand)[1]); break
                if cut is None:
                    continue
                k, q = cut
                new = self.dedupe([q] + list(pts[k + 1:]))
                if len(new) < 2:
                    t['dead'] = True; n += 1
                    break
                t['pts'] = new if end == 0 else new[::-1]; self.index_track(ti); n += 1
        self.purge_dead()
        return n

    def purge_dead(self):
        if not any(t.get('dead') for t in self.tracks):
            return
        for ti, t in enumerate(self.tracks):
            if t.get('dead'):
                for idx in self.track_items.get(ti, []):
                    self.cu.remove(idx)
        self.tracks = [t for t in self.tracks if not t.get('dead')]
        self.track_items = {}
        self.cu = Copper(self.outline)
        self.__init_static__()
        for ti in range(len(self.tracks)):
            self.index_track(ti)

    # connectivity audit (union-find over pads, vias and track segments)
    def net_pieces(self, net):
        items = []
        for p in self.pads:
            if p['net'] == net:
                r = max(p['size']) / 2 if p['shape'] == 'smd' else p['size'] / 2
                if len(p['layers']) == 2:
                    items.append(('v', None, (p['x'], p['y']), r, ('pad', p['ref'], p['pin'])))
                else:
                    items.append(('c', p['layers'][0], (p['x'], p['y']), r, ('pad', p['ref'], p['pin'])))
        for v in self.vias:
            if v['net'] == net:
                items.append(('v', None, (v['x'], v['y']), 0.3, None))
        for t in self.tracks:
            if t['net'] == net:
                for a, b in zip(t['pts'], t['pts'][1:]):
                    items.append(('s', t['layer'], (a, b), t['w'] / 2, None))
        parent = list(range(len(items)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        def touch(A, B):
            ka, La, ga, ra, _ = A; kb, Lb, gb, rb, _ = B
            if ka != 'v' and kb != 'v' and La != Lb: return False
            pa = ga if ka != 's' else None; pb = gb if kb != 's' else None
            if ka == 's' and kb == 's':
                return seg_seg_dist(ga[0], ga[1], gb[0], gb[1]) <= ra + rb + 1e-6
            if ka == 's':
                return point_seg_dist(gb, ga[0], ga[1]) <= ra + rb + 1e-6
            if kb == 's':
                return point_seg_dist(ga, gb[0], gb[1]) <= ra + rb + 1e-6
            return math.hypot(ga[0] - gb[0], ga[1] - gb[1]) <= ra + rb + 1e-6
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if touch(items[i], items[j]):
                    ri, rj = find(i), find(j)
                    if ri != rj: parent[ri] = rj
        pads_roots = {find(i) for i, it in enumerate(items) if it[4] is not None}
        return len(pads_roots)

    def audit(self, label):
        bad = [n for n in {t['net'] for t in self.tracks} if self.net_pieces(n) > 1]
        if bad:
            print(f'  !! after {label}: nets split: {bad}')
        return bad

    def on_other_track(self, ti, p):
        t = self.tracks[ti]
        for tj, o in enumerate(self.tracks):
            if tj == ti or o['net'] != t['net'] or o['layer'] != t['layer']: continue
            for a, b in zip(o['pts'], o['pts'][1:]):
                if point_seg_dist(p, a, b) <= o['w'] / 2 + 1e-6:
                    return True
        return False

    def junction_points(self, ti):
        """points where other same-net copper touches track ti: other track ends, via centres, pad centres."""
        t = self.tracks[ti]
        pts = []
        for tj, o in enumerate(self.tracks):
            if tj == ti or o['net'] != t['net'] or o['layer'] != t['layer']: continue
            pts += [o['pts'][0], o['pts'][-1]]
        pts += [(v['x'], v['y']) for v in self.vias if v['net'] == t['net']]
        pts += [(p['x'], p['y']) for p in self.pads if p['net'] == t['net'] and t['layer'] in p['layers']]
        return pts

    # --- 1. trim ends into pad / via centres
    def trim_ends(self):
        n_trim = 0
        for ti, t in enumerate(self.tracks):
            for end in (0, 1):
                pts = t['pts'] if end == 0 else t['pts'][::-1]
                p0 = pts[0]
                target = self.anchor_at(t['net'], t['layer'], p0)
                if target is None:
                    continue
                cx, cy, r = target
                # drop leading points that lie inside the anchor, then start from the centre
                k = 0
                while k < len(pts) - 1 and self.inside(pts[k], target):
                    k += 1
                new = [(cx, cy)] + list(pts[k:])
                if not is_octilinear(new[0], new[1]) and len(new) >= 2:
                    # make the exit octilinear if possible
                    for mid in octilinear(new[0], new[1]):
                        cand = [new[0]] + mid + new[1:]
                        if self.path_ok(ti, cand):
                            new = cand; break
                if new != list(pts):
                    n_trim += 1
                t['pts'] = new if end == 0 else new[::-1]
            t['pts'] = self.dedupe(t['pts'])
            self.index_track(ti)
        return n_trim

    def anchor_at(self, net, layer, p):
        """pad or via of the same net whose copper contains point p -> (cx, cy, r_equiv)."""
        for v in self.vias:
            if v['net'] == net and math.hypot(p[0] - v['x'], p[1] - v['y']) <= 0.31:
                return (v['x'], v['y'], 0.3)
        for pd in self.pads:
            if pd['net'] != net or layer not in pd['layers']: continue
            if pd['shape'] == 'smd':
                if abs(p[0] - pd['x']) <= pd['size'][0] / 2 + 1e-6 and abs(p[1] - pd['y']) <= pd['size'][1] / 2 + 1e-6:
                    return (pd['x'], pd['y'], max(pd['size']) / 2)
            elif pd['shape'] == 'rect':
                if abs(p[0] - pd['x']) <= pd['size'] / 2 + 1e-6 and abs(p[1] - pd['y']) <= pd['size'] / 2 + 1e-6:
                    return (pd['x'], pd['y'], pd['size'] / 2)
            elif math.hypot(p[0] - pd['x'], p[1] - pd['y']) <= pd['size'] / 2 + 1e-6:
                return (pd['x'], pd['y'], pd['size'] / 2)
        return None

    def inside(self, p, anchor):
        cx, cy, r = anchor
        return math.hypot(p[0] - cx, p[1] - cy) <= r + 1e-6

    @staticmethod
    def dedupe(pts):
        out = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
                out.append(p)
        # merge collinear
        res = [out[0]]
        for k in range(1, len(out) - 1):
            (x0, y0), (x1, y1), (x2, y2) = res[-1], out[k], out[k + 1]
            if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9 and (x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1) > 0:
                continue
            res.append(out[k])
        if len(out) > 1:
            res.append(out[-1])
        return res

    # --- 1b. remove tiny hook segments at track ends (typical where a hop meets a lane end)
    def remove_stubs(self, maxlen=0.4):
        n = 0
        for ti, t in enumerate(self.tracks):
            changed = True
            guard = 0
            while changed and len(t['pts']) >= 3 and guard < 8:
                guard += 1
                changed = False
                for end in (0, 1):
                    pts = t['pts'] if end == 0 else t['pts'][::-1]
                    if len(pts) < 3: continue
                    if math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) < maxlen:
                        for mid in ([[]] if is_octilinear(pts[0], pts[2]) else octilinear(pts[0], pts[2])):
                            cand = [pts[0]] + mid + list(pts[2:])
                            if len(cand) > len(pts) or math.hypot(cand[1][0] - cand[0][0], cand[1][1] - cand[0][1]) < maxlen:
                                continue
                            if all(math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-6 for a, b in zip(cand, pts)) and len(cand) == len(pts):
                                continue
                            if self.path_ok(ti, cand):
                                t['pts'] = cand if end == 0 else cand[::-1]
                                self.index_track(ti); n += 1; changed = True
                                break
                    if changed: break
            t['pts'] = self.dedupe(t['pts']); self.index_track(ti)
        return n

    # --- 1c. track ends that sit on another track (junction): slide the end along that track so
    #         the final approach is a single octilinear segment
    def snap_junction_ends(self, maxlen=2.0):
        n = 0
        for ti, t in enumerate(self.tracks):
            for end in (0, 1):
                pts = t['pts'] if end == 0 else t['pts'][::-1]
                if len(pts) < 3: continue
                p0, p1, p2 = pts[0], pts[1], pts[2]
                if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > maxlen: continue
                if self.anchor_at(t['net'], t['layer'], p0) is not None: continue   # pad/via end, not a junction
                host = None
                for tj, o in enumerate(self.tracks):
                    if tj == ti or o['net'] != t['net'] or o['layer'] != t['layer']: continue
                    for a, b in zip(o['pts'], o['pts'][1:]):
                        if point_seg_dist(p0, a, b) <= o['w'] / 2 + 1e-6 and (abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6):
                            host = (a, b); break
                    if host: break
                if host is None: continue
                a, b = host
                done = False
                # try to reach vertex k (3 first: drops two segments; then 2) with one octilinear segment
                for k in (3, 2):
                    if k >= len(pts) or done: continue
                    pk = pts[k]
                    cands = []
                    if abs(a[1] - b[1]) < 1e-6:        # horizontal host
                        yl = a[1]; dy = pk[1] - yl
                        for x in (pk[0] + abs(dy), pk[0] - abs(dy), pk[0]):
                            if min(a[0], b[0]) - 1e-6 <= x <= max(a[0], b[0]) + 1e-6:
                                cands.append((x, yl))
                    else:                               # vertical host
                        xl = a[0]; dx = pk[0] - xl
                        for y in (pk[1] + abs(dx), pk[1] - abs(dx), pk[1]):
                            if min(a[1], b[1]) - 1e-6 <= y <= max(a[1], b[1]) + 1e-6:
                                cands.append((xl, y))
                    for q in cands:
                        if not is_octilinear(q, pk): continue
                        cand = [q] + list(pts[k:])
                        if len(cand) >= 3:
                            # avoid creating a right angle at pk
                            v1 = (pk[0] - q[0], pk[1] - q[1]); v2 = (cand[2][0] - pk[0], cand[2][1] - pk[1])
                            L1, L2 = math.hypot(*v1), math.hypot(*v2)
                            if L1 > 1e-6 and L2 > 1e-6 and abs((v1[0] * v2[0] + v1[1] * v2[1]) / (L1 * L2)) < 0.05:
                                continue
                        if self.path_ok(ti, cand):
                            t['pts'] = cand if end == 0 else cand[::-1]
                            self.index_track(ti); n += 1; done = True
                            break
        return n

    # --- 2. straighten
    def straighten(self, passes=4):
        total = 0
        for _ in range(passes):
            changed = 0
            for ti, t in enumerate(self.tracks):
                pts = t['pts']
                i = 0
                new = [pts[0]]
                while i < len(pts) - 1:
                    best = None
                    for j in range(len(pts) - 1, i, -1):
                        a, b = pts[i], pts[j]
                        for mid in octilinear(a, b):
                            cand = [a] + mid + [b]
                            if len(cand) - 1 >= (j - i) and not (j - i == 1):
                                continue          # no gain
                            if j - i == 1 and not mid:
                                cand = None       # single segment already
                            if cand is None:
                                continue
                            if self.path_ok(ti, cand):
                                best = (j, cand); break
                        if best: break
                    if best:
                        j, cand = best
                        if cand[1:] != pts[i + 1:j + 1]:
                            changed += 1
                        new.extend(cand[1:])
                        i = j
                    else:
                        new.append(pts[i + 1]); i += 1
                new = self.dedupe(new)
                if new != pts:
                    t['pts'] = new
                    self.index_track(ti)
            total += changed
            if not changed:
                break
        return total

    # --- 3. chamfer 90-degree corners
    def chamfer(self, dmax=0.762):
        n = 0
        for ti, t in enumerate(self.tracks):
            pts = t['pts']
            k = 1
            while k < len(pts) - 1:
                a, b, c = pts[k - 1], pts[k], pts[k + 1]
                v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
                L1, L2 = math.hypot(*v1), math.hypot(*v2)
                if L1 < 1e-6 or L2 < 1e-6:
                    k += 1; continue
                cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (L1 * L2)
                if abs(cosang) < 0.05:          # 90 degrees
                    done = False
                    for dd in (dmax, 0.508, 0.254, 0.2, 0.15):
                        if dd > L1 - 0.01 or dd > L2 - 0.01:
                            continue
                        p1 = (b[0] - v1[0] / L1 * dd, b[1] - v1[1] / L1 * dd)
                        p2 = (b[0] + v2[0] / L2 * dd, b[1] + v2[1] / L2 * dd)
                        cand = pts[:k] + [p1, p2] + pts[k + 1:]
                        if self.path_ok(ti, cand):
                            pts = cand; t['pts'] = pts; self.index_track(ti); n += 1; done = True
                            k += 2
                            break
                    if not done:
                        k += 1
                else:
                    k += 1
        return n

    # --- 4. teardrops on every track end that sits on a pad or via centre
    def add_teardrops(self, L_via=0.70, L_pad=0.75, max_half=0.75):
        n = 0
        for ti, t in enumerate(self.tracks):
            for end in (0, 1):
                pts = t['pts'] if end == 0 else t['pts'][::-1]
                if len(pts) < 2: continue
                p0, p1 = pts[0], pts[1]
                seg = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                if seg < 1e-6: continue
                ux, uy = (p1[0] - p0[0]) / seg, (p1[1] - p0[1]) / seg
                nx, ny = -uy, ux
                w2 = t['w'] / 2
                base = None      # (corner_a, corner_b, L)
                for v in self.vias:
                    if v['net'] == t['net'] and math.hypot(p0[0] - v['x'], p0[1] - v['y']) < 1e-6:
                        rr = 0.3 * 0.85
                        base = ((v['x'] + nx * rr, v['y'] + ny * rr), (v['x'] - nx * rr, v['y'] - ny * rr), L_via); break
                if base is None:
                    for pd in self.pads:
                        if pd['net'] != t['net'] or t['layer'] not in pd['layers']: continue
                        if math.hypot(p0[0] - pd['x'], p0[1] - pd['y']) > 1e-6: continue
                        if pd['shape'] == 'circle':
                            r = pd['size'] / 2
                            rr = min(r * 0.85, max_half)
                            base = ((pd['x'] + nx * rr, pd['y'] + ny * rr), (pd['x'] - nx * rr, pd['y'] - ny * rr), L_pad + r * 0.4)
                        else:
                            hw, hh = (pd['size'][0] / 2, pd['size'][1] / 2) if pd['shape'] == 'smd' else (pd['size'] / 2, pd['size'] / 2)
                            # base corners: on the line through the pad centre normal to the track, then
                            # clamped INTO the pad rectangle (shrunk by 0.05) so nothing pokes out of the pad
                            rr = min(max(hw, hh), max_half)
                            tx = hw / abs(ux) if abs(ux) > 1e-9 else 1e9
                            ty = hh / abs(uy) if abs(uy) > 1e-9 else 1e9
                            edge = min(tx, ty)                      # centre -> pad boundary along the track
                            bx, by = pd['x'] + ux * edge * 0.5, pd['y'] + uy * edge * 0.5
                            def clamp(x, y):
                                return (min(max(x, pd['x'] - hw + 0.05), pd['x'] + hw - 0.05), min(max(y, pd['y'] - hh + 0.05), pd['y'] + hh - 0.05))
                            base = (clamp(bx + nx * rr, by + ny * rr), clamp(bx - nx * rr, by - ny * rr), edge + 0.55)
                        break
                if base is None:
                    continue
                ca, cb, L = base
                Ltot = min(L, seg)
                if Ltot < 0.3:
                    continue
                tx_, ty_ = p0[0] + ux * Ltot, p0[1] + uy * Ltot
                ta, tb = (tx_ + nx * w2, ty_ + ny * w2), (tx_ - nx * w2, ty_ - ny * w2)
                # each base corner must be behind or beside its track corner (no crossing, no splinter)
                proj_a = (ca[0] - p0[0]) * ux + (ca[1] - p0[1]) * uy
                proj_b = (cb[0] - p0[0]) * ux + (cb[1] - p0[1]) * uy
                if proj_a > Ltot - 0.15 or proj_b > Ltot - 0.15:
                    continue
                side_a = (ca[0] - p0[0]) * nx + (ca[1] - p0[1]) * ny
                side_b = (cb[0] - p0[0]) * nx + (cb[1] - p0[1]) * ny
                if side_a <= w2 + 0.03 or side_b >= -(w2 + 0.03):
                    continue          # base not wider than the track: no fillet worth drawing
                poly = [ca, ta, tb, cb]
                ok = True
                for a, b in ((poly[0], poly[1]), (poly[3], poly[2]), (poly[0], poly[3])):
                    if self.cu.clearance_seg(t['net'], t['layer'], a, b, 0.0, ignore={('t', ti)}) < 0:
                        ok = False; break
                if ok:
                    self.teardrops.append(dict(net=t['net'], layer=t['layer'], pts=poly))
                    n += 1
        return n

    # --- stats
    def stats(self):
        segs = bends90 = bends = 0
        for t in self.tracks:
            pts = t['pts']; segs += len(pts) - 1
            for k in range(1, len(pts) - 1):
                a, b, c = pts[k - 1], pts[k], pts[k + 1]
                v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
                L1, L2 = math.hypot(*v1), math.hypot(*v2)
                if L1 < 1e-6 or L2 < 1e-6: continue
                cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (L1 * L2)
                if cosang < 0.98: bends += 1
                if abs(cosang) < 0.05: bends90 += 1
        return dict(segments=segs, bends=bends, right_angles=bends90, tracks=len(self.tracks))

def run(variant):
    d = json.load(open(f'layout_{variant}.json'))
    if 'teardrops' in d: del d['teardrops']
    c = Cleaner(d)
    print(f'[{variant}] before: {c.stats()}')
    c.audit('load')
    steps = [('split at junctions', c.split_at_junctions), ('merged end-to-end tracks', c.merge_degree2), ('trimmed dangling ends', c.trim_dangling),
             ('merged end-to-end tracks (2nd)', c.merge_degree2), ('trimmed ends', c.trim_ends), ('removed end stubs', c.remove_stubs),
             ('snapped junction ends', c.snap_junction_ends), ('straightened runs', c.straighten),
             ('chamfered corners', c.chamfer), ('trimmed dangling ends (2nd)', c.trim_dangling),
             ('merged end-to-end tracks (3rd)', c.merge_degree2), ('removed end stubs (2nd)', c.remove_stubs), ('snapped junction ends (2nd)', c.snap_junction_ends),
             ('straightened runs (2nd)', c.straighten), ('chamfered corners (2nd)', c.chamfer),
             ('trimmed dangling ends (3rd)', c.trim_dangling)]
    for label, fn in steps:
        print(f'  {label}: {fn()}')
        c.audit(label)
    for t in c.tracks:
        if len(t['pts']) < 2: t['dead'] = True
    c.purge_dead()
    print(f'  teardrops: {c.add_teardrops()}')
    print(f'[{variant}] after: {c.stats()}')
    d['tracks'] = [dict(net=t['net'], layer=t['layer'], pts=[list(p) for p in t['pts']], w=t['w']) for t in c.tracks]
    d['teardrops'] = [dict(net=td['net'], layer=td['layer'], pts=[list(p) for p in td['pts']]) for td in c.teardrops]
    # regenerate the pour with teardrops as conservative pseudo-tracks
    pseudo = d['tracks'] + [dict(net=td['net'], layer=td['layer'], pts=[list(p) for p in td['pts']] + [list(td['pts'][0])], w=0.05) for td in c.teardrops]
    pours = {}
    for layer, net in POUR_NETS.items():
        R, mask = make_pour(d, layer, net, tracks=pseudo)
        outers, holes = mask_polygons(R, mask)
        pours[layer] = dict(net=net, outers=outers, holes=holes, segs=[])
    d['pours'] = pours
    json.dump(d, open(f'layout_{variant}.json', 'w'))

if __name__ == '__main__':
    for v in sys.argv[1:] or ['U', 'L']:
        run(v)
