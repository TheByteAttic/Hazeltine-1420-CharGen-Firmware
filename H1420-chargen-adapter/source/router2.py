# Copyright (c) 2026 by The Byte Attic B.V.
"""Negotiated-congestion (PathFinder-style) 45-degree grid router."""
import math, heapq, time
import numpy as np
from scipy import ndimage
from board import Pad, Track, Via, build_pads, point_in_poly, seg_dist2, DIRS, STEP, EDGE_KEEP, CLEAR
from design import outline, preroutes, NETS, BOARD_W

TRACE_W = 0.20
POWER_W = 0.40
VIA_D, VIA_DRILL = 0.60, 0.30
PAD_CLEAR = 0.30        # trace-to-pad clearance (track-to-track stays CLEAR = 0.20)
DIAG_MARGIN = 0.18      # a 45-degree segment passes closer to obstacles than its cell centres

class PFRouter:
    def __init__(self, variant, use_preroutes=True):
        self.variant = variant
        self.pads = build_pads(variant)
        self.poly = outline(variant)
        ys_ = [p[1] for p in self.poly]
        self.ymin = math.floor(min(ys_) / STEP) * STEP
        self.NX = int(round(BOARD_W / STEP)) + 1
        self.NY = int(round((max(ys_) - self.ymin) / STEP)) + 1
        xs = np.arange(self.NX) * STEP
        ys = self.ymin + np.arange(self.NY) * STEP
        self.gx, self.gy = np.meshgrid(xs, ys, indexing='ij')
        inside = point_in_poly(self.gx, self.gy, self.poly)
        d2 = np.full(self.gx.shape, np.inf)
        n = len(self.poly)
        for i in range(n):
            x1, y1 = self.poly[i]; x2, y2 = self.poly[(i + 1) % n]
            d2 = np.minimum(d2, seg_dist2(self.gx, self.gy, x1, y1, x2, y2))
        self.edge_d = np.sqrt(d2)
        self.inside = inside
        self.nets = list(NETS.keys())
        self.nid = {n: k for k, n in enumerate(self.nets)}
        # static pad maps: pad_owner[L] (net id or -1 at cells inside a pad), pad_block[L, net] computed lazily
        self.static_block = {}       # net -> [2, NX, NY] bool (other nets' pads expanded + edge)
        self.static_via_ok = {}      # net -> [NX, NY]
        self.padcells = {}           # net -> set of (li, i, j)
        for p in self.pads:
            for L in p.layers():
                li = 0 if L == 'top' else 1
                for (i, j) in self.cells_in_pad(p):
                    self.padcells.setdefault(p.net, set()).add((li, i, j))
        # dynamic: per-net routed cells; occupancy of trace centres per layer, via centres
        self.route_cells = {n: set() for n in self.nets}    # (li, i, j) trace/via centre cells
        self.via_cells = {n: set() for n in self.nets}      # (i, j)
        self.via_forbid = {n: set() for n in self.nets}     # (i, j) cells where this net may not place a via
        self.occ = np.zeros((2, self.NX, self.NY), np.int16)   # count of nets with a centre at cell
        self.occ_wide = np.zeros((2, self.NX, self.NY), np.int16)  # same, wide (power) nets only
        self.wide = {'GND', 'VCC'}
        self.occ_soft = np.zeros((2, self.NX, self.NY), np.int16)
        self.soft = {n: set() for n in self.nets}
        self.vocc = np.zeros((self.NX, self.NY), np.int16)     # via centres
        self.hist = np.zeros((2, self.NX, self.NY), np.float32)
        self.fixed = {n: set() for n in self.nets}          # pre-routed cells (never ripped up)
        self.connected = {n: set() for n in self.nets}
        self.tracks_fixed = []
        if use_preroutes:
            for (net, layer, pts, w) in preroutes(variant):
                li = 0 if layer == 'top' else 1
                cells = set()
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    nseg = max(1, int(round(math.hypot(x2 - x1, y2 - y1) / STEP)))
                    for k in range(nseg + 1):
                        cells.add((li,) + self.ij(x1 + (x2 - x1) * k / nseg, y1 + (y2 - y1) * k / nseg))
                self.fixed[net] |= cells
                self.tracks_fixed.append(Track(net, layer, list(pts), w))
                for (li_, i, j) in cells:
                    self.occ[li_, i, j] += 1
                    if net in self.wide: self.occ_wide[li_, i, j] += 1
                self.route_cells[net] |= cells

    def add_fixed_cells(self, net, cells):
        """Register externally generated copper (a pour) as fixed 'soft' cells of `net`: they are
        connection targets and count as obstacles with the plain 3x3 rule only (the pour is
        regenerated afterwards with full clearance around whatever gets routed)."""
        new = set(cells) - self.fixed[net]
        self.fixed[net] |= new
        for (li, i, j) in new:
            if (li, i, j) not in self.route_cells[net]:
                self.occ_soft[li, i, j] += 1
                self.route_cells[net].add((li, i, j))
        self.soft[net] |= new

    def ij(self, x, y):
        return int(round(x / STEP)), int(round((y - self.ymin) / STEP))
    def xy(self, i, j):
        return i * STEP, self.ymin + j * STEP

    def cells_in_pad(self, p):
        r = p.radius + 0.01
        i0, j0 = self.ij(p.x - r, p.y - r); i1, j1 = self.ij(p.x + r, p.y + r)
        out = []
        for i in range(max(0, i0), min(self.NX - 1, i1) + 1):
            for j in range(max(0, j0), min(self.NY - 1, j1) + 1):
                x, y = self.xy(i, j)
                if p.smd:
                    if abs(x - p.x) <= p.size[0] / 2 + 1e-6 and abs(y - p.y) <= p.size[1] / 2 + 1e-6:
                        out.append((i, j))
                elif math.hypot(x - p.x, y - p.y) <= p.size / 2 + 1e-6:
                    out.append((i, j))
        return out

    def box(self, x, y, d):
        i0, j0 = self.ij(x - d, y - d); i1, j1 = self.ij(x + d, y + d)
        i0, j0, i1, j1 = max(0, i0 - 1), max(0, j0 - 1), min(self.NX, i1 + 2), min(self.NY, j1 + 2)
        return (i0, i1, j0, j1) if i0 < i1 and j0 < j1 else None

    def pad_block(self, net, halfw, margin=0.0):
        """cells where a trace centre of `net` (half width halfw) would violate a pad of another net or the edge."""
        base = (~self.inside) | (self.edge_d < EDGE_KEEP + halfw)
        blocked = np.stack([base.copy(), base.copy()])
        for p in self.pads:
            if p.net == net: continue
            for L in p.layers():
                li = 0 if L == 'top' else 1
                if p.smd:
                    hw, hh = p.size[0] / 2, p.size[1] / 2
                    d = PAD_CLEAR + halfw + margin
                    b = self.box(p.x, p.y, max(hw, hh) + d)
                    if not b: continue
                    i0, i1, j0, j1 = b
                    gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                    ddx = np.maximum(np.abs(gx - p.x) - hw, 0); ddy = np.maximum(np.abs(gy - p.y) - hh, 0)
                    blocked[li, i0:i1, j0:j1] |= ddx * ddx + ddy * ddy < d * d
                else:
                    d = p.radius + PAD_CLEAR + halfw + margin
                    b = self.box(p.x, p.y, d)
                    if not b: continue
                    i0, i1, j0, j1 = b
                    gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                    blocked[li, i0:i1, j0:j1] |= (gx - p.x) ** 2 + (gy - p.y) ** 2 < d * d
        for (li, i, j) in self.padcells.get(net, ()):
            blocked[li, i, j] = False
        return blocked

    def static_maps(self, net, halfw):
        key = (net, halfw)
        if key not in self.static_block:
            self.static_block[key] = (self.pad_block(net, halfw), self.pad_block(net, halfw, DIAG_MARGIN))
        if net not in self.static_via_ok:
            b = self.pad_block(net, VIA_D / 2)
            ok = ~(b[0] | b[1])
            for p in self.pads:
                d = p.radius + (PAD_CLEAR if p.net != net else 0.1) + VIA_D / 2
                bx = self.box(p.x, p.y, d)
                if not bx: continue
                i0, i1, j0, j1 = bx
                gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                ok[i0:i1, j0:j1] &= (gx - p.x) ** 2 + (gy - p.y) ** 2 >= d * d
            self.static_via_ok[net] = ok
        return self.static_block[key], self.static_via_ok[net]

    # ------------------------------------------------------------ occupancy
    def rip_up(self, net):
        for (li, i, j) in self.route_cells[net] - self.fixed[net]:
            self.occ[li, i, j] -= 1
            if net in self.wide: self.occ_wide[li, i, j] -= 1
        for (i, j) in self.via_cells[net]:
            self.vocc[i, j] -= 1
        self.route_cells[net] = set(self.fixed[net])
        self.via_cells[net] = set()

    def others_near(self, net):
        """[2, NX, NY] count of OTHER nets' centre cells near each cell (3x3 for normal/normal pairs,
        5x5 when either net is wide), plus a via conflict map [NX, NY] (5x5 on either layer)."""
        occ_n = self.occ.astype(np.float32) - self.occ_wide.astype(np.float32)
        occ_w = self.occ_wide.astype(np.float32)
        own = np.zeros_like(occ_n)
        for (li, i, j) in self.route_cells[net] - self.soft[net]:
            own[li, i, j] += 1
        if net in self.wide:
            occ_w = occ_w - own
        else:
            occ_n = occ_n - own
        soft = self.occ_soft.astype(np.float32)
        for (li, i, j) in self.soft[net]:
            soft[li, i, j] -= 1
        # neighbourhood kernels for the 0.254 mm grid with 0.20 mm traces:
        #   normal-normal: 3x3 (2-cell spacing: 0.508 orth -> 0.31 clearance, 0.359 diag -> 0.16)
        #   wide involved: 5x5 minus orthogonal end cells (0.508 orth ok, diagonals need 3 cells)
        #   vias: 5x5
        K3 = np.ones((3, 3), np.float32)
        K_W = np.ones((5, 5), np.float32); K_W[0, 2] = K_W[4, 2] = K_W[2, 0] = K_W[2, 4] = 0
        # vias: JLCPCB hole-to-hole >= 0.5 mm edge to edge -> via centres >= 0.8 mm apart -> every cell
        # with di^2 + dj^2 <= 9 (0.762 mm) around a via is a conflict (7x7 disk)
        yy, xx = np.ogrid[-3:4, -3:4]
        K_V = ((xx * xx + yy * yy) <= 9).astype(np.float32)
        K5 = np.ones((5, 5), np.float32)              # via vs other nets' traces
        kn = K_W if net in self.wide else K3
        near = np.stack([ndimage.convolve(occ_n[k], kn, mode='constant') +
                         ndimage.convolve(occ_w[k], K_W, mode='constant') +
                         ndimage.convolve(soft[k], K3, mode='constant') for k in range(2)])
        vo = self.vocc.astype(np.float32)
        vown = np.zeros_like(vo)
        for (i, j) in self.via_cells[net]:
            vown[i, j] += 1
        v = vo - vown
        o = occ_n + occ_w + soft
        vnear = ndimage.convolve(v, K_V, mode='constant')
        tnear5 = ndimage.convolve(o[0] + o[1], K5, mode='constant')
        near = near + np.stack([ndimage.convolve(v, K5, mode='constant')] * 2)
        return np.round(near), np.round(vnear + tnear5)

    # ------------------------------------------------------------ routing
    def route_net(self, net, width, pres_fac, bend_cost=3.5, via_cost=10.0):
        pads = [p for p in self.pads if p.net == net]
        if len(pads) < 2:
            return True
        self.rip_up(net)
        (blocked, blocked_d), via_ok = self.static_maps(net, width / 2)
        if self.via_forbid[net]:
            via_ok = via_ok.copy()
            for (i, j) in self.via_forbid[net]:
                via_ok[i, j] = False
        near, vnear = self.others_near(net)
        cx, cy = np.mean([p.x for p in pads]), np.mean([p.y for p in pads])
        remaining = sorted(pads, key=lambda p: math.hypot(p.x - cx, p.y - cy))
        if self.fixed[net]:
            # pre-routed copper is the seed: every pad must be connected to it
            fx = [self.xy(i, j) for (_, i, j) in self.fixed[net]]
            done = []
            near_fixed = lambda p: min(math.hypot(p.x - x, p.y - y) for (x, y) in fx)
            self.connected[net] = set(self.fixed[net])
        else:
            done = [remaining.pop(0)]
            self.connected[net] = {(0 if L == 'top' else 1,) + c for L in done[0].layers() for c in self.cells_in_pad(done[0])}
        ok_all = True
        while remaining:
            if done:
                best = min(remaining, key=lambda p: min(math.hypot(p.x - q.x, p.y - q.y) for q in done))
            else:
                best = min(remaining, key=near_fixed)
            remaining.remove(best)
            path = self.search(net, best, blocked, blocked_d, via_ok, near, vnear, pres_fac, bend_cost, via_cost)
            if path is None:
                ok_all = False
                break
            self.commit(net, path)
            self.connected[net] |= set(path)
            self.connected[net] |= {(0 if L == 'top' else 1,) + c for L in best.layers() for c in self.cells_in_pad(best)}
            done.append(best)
        return ok_all

    def search(self, net, pad, blocked, blocked_d, via_ok, near, vnear, pres_fac, bend_cost, via_cost):
        NX, NY = self.NX, self.NY
        start_cells = {(0 if L == 'top' else 1,) + c for L in pad.layers() for c in self.cells_in_pad(pad)}
        targets = self.connected[net] - start_cells
        if not targets:
            return None
        tgt = np.zeros((2, NX, NY), bool)
        for (li, i, j) in targets:
            tgt[li, i, j] = True
        # heuristic: euclidean cell distance to nearest target (either layer)
        anyt = tgt[0] | tgt[1]
        h = ndimage.distance_transform_edt(~anyt)
        INF = 1e18
        dist = np.full((2, NX, NY, 9), INF, np.float64)
        prev = {}
        heap = []
        for (li, i, j) in start_cells:
            dist[li, i, j, 8] = 0
            heapq.heappush(heap, (h[i, j], 0.0, li, i, j, 8))
        found = None
        SQ2 = math.sqrt(2)
        while heap:
            f, d, li, i, j, dr = heapq.heappop(heap)
            if d > dist[li, i, j, dr]: continue
            if tgt[li, i, j]:
                found = (li, i, j, dr); break
            for nd_, (di, dj) in enumerate(DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < NX and 0 <= nj < NY) or blocked[li, ni, nj]:
                    continue
                if di and dj:
                    if blocked[li, i + di, j] or blocked[li, i, j + dj] or blocked_d[li, ni, nj] or blocked_d[li, i, j]:
                        continue
                    c = SQ2
                else:
                    c = 1.0
                if dr != 8 and dr != nd_:
                    a1 = math.atan2(DIRS[dr][1], DIRS[dr][0]); a2 = math.atan2(dj, di)
                    ang = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
                    c += bend_cost * (ang / (math.pi / 4))
                c += pres_fac * near[li, ni, nj] + self.hist[li, ni, nj]
                nd = d + c
                if nd < dist[li, ni, nj, nd_]:
                    dist[li, ni, nj, nd_] = nd; prev[(li, ni, nj, nd_)] = (li, i, j, dr)
                    heapq.heappush(heap, (nd + h[ni, nj], nd, li, ni, nj, nd_))
            if via_ok[i, j] and not blocked[1 - li, i, j]:
                c = via_cost + pres_fac * vnear[i, j] + self.hist[li, i, j] + self.hist[1 - li, i, j]
                nd = d + c
                if nd < dist[1 - li, i, j, 8]:
                    dist[1 - li, i, j, 8] = nd; prev[(1 - li, i, j, 8)] = (li, i, j, dr)
                    heapq.heappush(heap, (nd + h[i, j], nd, 1 - li, i, j, 8))
        if found is None:
            return None
        path = [found]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        return [(li, i, j) for (li, i, j, _) in path]

    def commit(self, net, path):
        for a, b in zip(path, path[1:]):
            if a[0] != b[0]:
                self.via_cells[net].add((a[1], a[2]))
                self.vocc[a[1], a[2]] += 1
        for c in path:
            if c not in self.route_cells[net]:
                self.route_cells[net].add(c)
                self.occ[c[0], c[1], c[2]] += 1
                if net in self.wide: self.occ_wide[c[0], c[1], c[2]] += 1
        self.paths = getattr(self, 'paths', {})
        self.paths.setdefault(net, []).append(path)

    def conflicts(self):
        """Return set of nets that currently conflict with another net."""
        bad = set()
        for net in self.nets:
            near, vnear = self.others_near(net)
            for (li, i, j) in self.route_cells[net] - self.fixed[net]:
                if near[li, i, j] > 0:
                    bad.add(net); break
            else:
                for (i, j) in self.via_cells[net]:
                    if vnear[i, j] > 0:
                        bad.add(net); break
                else:
                    # own vias too close to each other (hole-to-hole rule is net independent)
                    vc = sorted(self.via_cells[net])
                    for a in range(len(vc)):
                        for b in range(a + 1, len(vc)):
                            if (vc[a][0] - vc[b][0]) ** 2 + (vc[a][1] - vc[b][1]) ** 2 <= 9:
                                self.via_forbid[net].add(vc[b])
                                bad.add(net)
        return bad

    def run(self, order, widths, iters=30, log=print):
        pres = 0.5
        if not hasattr(self, 'paths'):
            self.paths = {}
        for it in range(iters):
            t0 = time.time()
            unrouted = []
            for net in order:
                self.paths[net] = []
                if not self.route_net(net, widths.get(net, TRACE_W), pres):
                    unrouted.append(net)
            bad = self.conflicts() & set(order)
            # history update on conflicting cells
            occ_near = np.stack([ndimage.uniform_filter(self.occ[k].astype(np.float32), size=3, mode='constant') * 9 for k in range(2)])
            self.hist += (np.round(occ_near) > 1).astype(np.float32) * 1.0
            log(f'  iter {it}: {len(bad)} conflicting nets, {len(unrouted)} unrouted, pres={pres:.1f}, {time.time()-t0:.0f}s')
            if not bad and not unrouted:
                return True
            pres *= 1.3
        return False

    # ------------------------------------------------------------ export geometry
    def geometry(self, widths):
        tracks = list(self.tracks_fixed)
        vias = []
        for net, plist in self.paths.items():
            w = widths.get(net, TRACE_W)
            for path in plist:
                cur = [path[0]]
                for a, b in zip(path, path[1:]):
                    if a[0] != b[0]:
                        tracks.append(self.polyline(net, cur, w))
                        x, y = self.xy(a[1], a[2])
                        vias.append(Via(net, x, y))
                        cur = [b]
                    else:
                        cur.append(b)
                tracks.append(self.polyline(net, cur, w))
        return [t for t in tracks if t is not None], vias

    def polyline(self, net, cells, w):
        if len(cells) < 2:
            return None
        layer = 'top' if cells[0][0] == 0 else 'bot'
        pts = [self.xy(i, j) for (_, i, j) in cells]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = out[-1], pts[k], pts[k + 1]
            if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9:
                continue
            out.append(pts[k])
        out.append(pts[-1])
        return Track(net, layer, out, w)
