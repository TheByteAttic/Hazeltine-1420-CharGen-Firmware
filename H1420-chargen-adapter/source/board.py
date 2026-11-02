# Copyright (c) 2026 by The Byte Attic B.V.
"""Board geometry model + 45-degree grid router with bend penalty."""
import math, heapq
import numpy as np
from design import placed_pads, outline, preroutes, NETS, BOARD_W

TRACE_W = 0.25
POWER_W = 0.45
CLEAR = 0.20            # copper-to-copper clearance (JLCPCB minimum 0.127)
VIA_D, VIA_DRILL = 0.70, 0.35
STEP = 0.254            # routing grid = 1/10 of 0.1"
EDGE_KEEP = 0.5         # copper-to-board-edge

class Pad:
    def __init__(self, ref, pin, x, y, hole, size, shape, layers, net):
        self.ref, self.pin, self.x, self.y = ref, pin, x, y
        self.hole, self.size, self.shape, self.lay, self.net = hole, size, shape, layers, net
        self.smd = shape == 'smd'
    @property
    def radius(self):
        if self.smd:
            return math.hypot(*self.size) / 2
        return self.size * math.sqrt(2) / 2 if self.shape == 'rect' else self.size / 2
    def layers(self):
        return self.lay

class Track:
    def __init__(self, net, layer, pts, w):
        self.net, self.layer, self.pts, self.w = net, layer, pts, w

class Via:
    def __init__(self, net, x, y):
        self.net, self.x, self.y = net, x, y

def build_pads(variant):
    return [Pad(*t) for t in placed_pads(variant)]

def point_in_poly(px, py, poly):
    """vectorised even-odd test; px, py arrays."""
    inside = np.zeros_like(px, dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > py) != (y2 > py))
        with np.errstate(divide='ignore', invalid='ignore'):
            xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1) if y2 != y1 else np.full_like(px, np.inf)
        inside ^= cond & (px < xint)
    return inside

def seg_dist2(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0, 1)
    return (px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2

DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]

class Router:
    def __init__(self, variant):
        self.variant = variant
        self.pads = build_pads(variant)
        self.poly = outline(variant)
        self.tracks, self.vias = [], []
        ys_ = [p[1] for p in self.poly]
        self.ymin = math.floor(min(ys_) / STEP) * STEP
        self.NX = int(round(BOARD_W / STEP)) + 1
        self.NY = int(round((max(ys_) - self.ymin) / STEP)) + 1
        xs = np.arange(self.NX) * STEP
        ys = self.ymin + np.arange(self.NY) * STEP
        self.gx, self.gy = np.meshgrid(xs, ys, indexing='ij')
        # inside-board mask with edge keep-out (shrunk polygon approximated by distance to edges)
        inside = point_in_poly(self.gx, self.gy, self.poly)
        d2 = np.full(self.gx.shape, np.inf)
        n = len(self.poly)
        for i in range(n):
            x1, y1 = self.poly[i]; x2, y2 = self.poly[(i + 1) % n]
            d2 = np.minimum(d2, seg_dist2(self.gx, self.gy, x1, y1, x2, y2))
        self.edge_d = np.sqrt(d2)
        self.inside = inside
        self.circ = {'top': [], 'bot': []}       # (x, y, r, net)
        self.rects = {'top': [], 'bot': []}      # (x, y, hw, hh, net) axis-aligned SMD pads
        self.segs = {'top': [], 'bot': []}       # (x1, y1, x2, y2, w, net)
        for p in self.pads:
            for L in p.layers():
                if p.smd:
                    self.rects[L].append((p.x, p.y, p.size[0] / 2, p.size[1] / 2, p.net))
                else:
                    self.circ[L].append((p.x, p.y, p.radius, p.net))
        self.padcells = {}
        for p in self.pads:
            for L in p.layers():
                for c in self.cells_in_pad(p):
                    self.padcells.setdefault(p.net, set()).add((L,) + c)

    def preroute(self):
        for (net, layer, pts, w) in preroutes(self.variant):
            self.tracks.append(Track(net, layer, list(pts), w))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                self.segs[layer].append((x1, y1, x2, y2, w, net))

    # ------------------------------------------------------------ grid helpers
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

    def blocked_map(self, net, halfw):
        """[2, self.NX, self.NY] True where copper of `net` with half-width halfw may NOT be centred."""
        base = (~self.inside) | (self.edge_d < EDGE_KEEP + halfw)
        blocked = np.stack([base.copy(), base.copy()])
        for li, L in enumerate(('top', 'bot')):
            for (x, y, r, n) in self.circ[L]:
                if n == net: continue
                d = r + CLEAR + halfw
                b = self.box(x, y, d)
                if not b: continue
                i0, i1, j0, j1 = b
                gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                blocked[li, i0:i1, j0:j1] |= (gx - x) ** 2 + (gy - y) ** 2 < d * d
            for (x, y, hw, hh, n) in self.rects[L]:
                if n == net: continue
                d = CLEAR + halfw
                b = self.box(x, y, max(hw, hh) + d)
                if not b: continue
                i0, i1, j0, j1 = b
                gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                ddx = np.maximum(np.abs(gx - x) - hw, 0); ddy = np.maximum(np.abs(gy - y) - hh, 0)
                blocked[li, i0:i1, j0:j1] |= ddx * ddx + ddy * ddy < d * d
            for (x1, y1, x2, y2, w, n) in self.segs[L]:
                if n == net: continue
                d = w / 2 + CLEAR + halfw
                b = self.box(min(x1, x2), min(y1, y2), 0)
                i0, j0 = self.ij(min(x1, x2) - d, min(y1, y2) - d); i1, j1 = self.ij(max(x1, x2) + d, max(y1, y2) + d)
                i0, j0, i1, j1 = max(0, i0 - 1), max(0, j0 - 1), min(self.NX, i1 + 2), min(self.NY, j1 + 2)
                gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
                blocked[li, i0:i1, j0:j1] |= seg_dist2(gx, gy, x1, y1, x2, y2) < d * d
        for (L, i, j) in self.padcells.get(net, ()):
            blocked[0 if L == 'top' else 1, i, j] = False
        return blocked

    def via_ok_map(self, net):
        b = self.blocked_map(net, VIA_D / 2)
        ok = ~(b[0] | b[1])
        for p in self.pads:                     # never put a via in or hugging a pad
            d = p.radius + (CLEAR if p.net != net else 0.15) + VIA_D / 2
            bx = self.box(p.x, p.y, d)
            if not bx: continue
            i0, i1, j0, j1 = bx
            gx, gy = self.gx[i0:i1, j0:j1], self.gy[i0:i1, j0:j1]
            ok[i0:i1, j0:j1] &= (gx - p.x) ** 2 + (gy - p.y) ** 2 >= d * d
        return ok

    def net_cells(self, net):
        cells = set(self.padcells.get(net, ()))
        for t in self.tracks:
            if t.net != net: continue
            for (x1, y1), (x2, y2) in zip(t.pts, t.pts[1:]):
                n = max(1, int(round(math.hypot(x2 - x1, y2 - y1) / STEP)))
                for k in range(n + 1):
                    cells.add((t.layer,) + self.ij(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n))
        for v in self.vias:
            if v.net != net: continue
            i, j = self.ij(v.x, v.y)
            cells.add(('top', i, j)); cells.add(('bot', i, j))
        return cells

    # ------------------------------------------------------------ routing
    def route_net(self, net, width=TRACE_W, via_cost=14.0, bend_cost=2.5, log=print):
        pads = [p for p in self.pads if p.net == net]
        if len(pads) < 2:
            return True
        cx, cy = np.mean([p.x for p in pads]), np.mean([p.y for p in pads])
        remaining = sorted(pads, key=lambda p: math.hypot(p.x - cx, p.y - cy))
        first = remaining.pop(0)
        done = [first]
        while remaining:
            best = min(remaining, key=lambda p: min(math.hypot(p.x - q.x, p.y - q.y) for q in done))
            remaining.remove(best)
            if not self.connect(net, best, width, via_cost, bend_cost):
                log(f'  FAILED to route {net} to {best.ref}.{best.pin}')
                return False
            done.append(best)
        return True

    def connect(self, net, pad, width, via_cost, bend_cost):
        blocked = self.blocked_map(net, width / 2)
        via_ok = self.via_ok_map(net)
        start_cells = {(L,) + c for L in pad.layers() for c in self.cells_in_pad(pad)}
        targets = self.net_cells(net) - start_cells
        if not targets:
            return False
        tgt = np.zeros((2, self.NX, self.NY), bool)
        for (L, i, j) in targets:
            tgt[0 if L == 'top' else 1, i, j] = True
        INF = 1e18
        # state: (layer, i, j, dir) dir 0..7 or 8 (none)
        dist = np.full((2, self.NX, self.NY, 9), INF)
        prev = {}
        heap = []
        for (L, i, j) in start_cells:
            li = 0 if L == 'top' else 1
            dist[li, i, j, 8] = 0
            heapq.heappush(heap, (0.0, li, i, j, 8))
        found = None
        while heap:
            d, li, i, j, dr = heapq.heappop(heap)
            if d > dist[li, i, j, dr]: continue
            if tgt[li, i, j]:
                found = (li, i, j, dr); break
            for nd_, (di, dj) in enumerate(DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.NX and 0 <= nj < self.NY) or blocked[li, ni, nj]:
                    continue
                if di and dj:  # diagonal: both orthogonal neighbours must be free (no corner cutting)
                    if blocked[li, i + di, j] or blocked[li, i, j + dj]:
                        continue
                    c = math.sqrt(2)
                else:
                    c = 1.0
                if dr != 8 and dr != nd_:
                    # penalise bends; 45-degree bends cheaper than 90-degree ones
                    a1 = math.atan2(DIRS[dr][1], DIRS[dr][0]); a2 = math.atan2(dj, di)
                    ang = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
                    c += bend_cost * (ang / (math.pi / 4))
                nd = d + c
                if nd < dist[li, ni, nj, nd_]:
                    dist[li, ni, nj, nd_] = nd; prev[(li, ni, nj, nd_)] = (li, i, j, dr)
                    heapq.heappush(heap, (nd, li, ni, nj, nd_))
            if via_ok[i, j] and not blocked[1 - li, i, j]:
                nd = d + via_cost
                if nd < dist[1 - li, i, j, 8]:
                    dist[1 - li, i, j, 8] = nd; prev[(1 - li, i, j, 8)] = (li, i, j, dr)
                    heapq.heappush(heap, (nd, 1 - li, i, j, 8))
        if found is None:
            return False
        path = [found]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        self.commit(net, [(li, i, j) for (li, i, j, _) in path], width)
        return True

    def commit(self, net, path, width):
        cur = [path[0]]
        for a, b in zip(path, path[1:]):
            if a[0] != b[0]:
                self.add_track(net, cur, width)
                x, y = self.xy(a[1], a[2])
                self.vias.append(Via(net, x, y))
                for L in ('top', 'bot'):
                    self.circ[L].append((x, y, VIA_D / 2, net))
                cur = [b]
            else:
                cur.append(b)
        self.add_track(net, cur, width)

    def add_track(self, net, cells, width):
        if len(cells) < 2:
            return
        layer = 'top' if cells[0][0] == 0 else 'bot'
        pts = [self.xy(i, j) for (_, i, j) in cells]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = out[-1], pts[k], pts[k + 1]
            if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9:
                continue
            out.append(pts[k])
        out.append(pts[-1])
        self.tracks.append(Track(net, layer, out, width))
        for (x1, y1), (x2, y2) in zip(out, out[1:]):
            self.segs[layer].append((x1, y1, x2, y2, width, net))
