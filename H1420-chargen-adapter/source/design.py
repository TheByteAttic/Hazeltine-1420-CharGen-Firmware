# Copyright (c) 2026 by The Byte Attic B.V.
"""
DM8678 / DM86S64 character-generator replacement adapter for the Hazeltine 1420 (U25/U26).

Two mirror-image variants:
  variant 'U' : for the UPPER socket (U26) - body extends upward (+y), away from U25
  variant 'L' : for the LOWER socket (U25) - body extends downward (-y), away from U26

Frame: x to the right, y up, viewed from the component (top) side.  The plug footprint
(P1) sits at the right end of the narrow neck and plugs into the DIP-16 socket, whose
notch / pin 1 is at the LEFT end of the socket (pin 1 bottom-left, pin 16 top-left).
The board extends to the left of the socket.  All dimensions mm; placement grid 1.27 mm.
"""
import sys
U = 1.27
VARIANT = 'U'

# ---------------------------------------------------------------- outline (variant U; mirrored for L)
NECK_W = 11 * U          # 13.97 - neck width (socket body is ~10.7 mm, sockets ~17 mm apart)
NECK_L = 23 * U          # 29.21 - neck length (covers the 20 mm socket + 9 mm)
BODY_W = 19 * U          # 24.13 - body width (neck + 10.16 mm outward)
BODY_L = 40 * U          # 50.80 - body length
BOARD_W = NECK_L + BODY_L   # 74.93
NY0 = 0.0                # neck bottom edge (y)  -> neck spans y 0 .. NECK_W
CY = NECK_W / 2          # 6.35 - socket centreline
# outline polygon (counter-clockwise), variant U
OUTLINE_U = [(0, 0), (BOARD_W, 0), (BOARD_W, NECK_W), (BODY_L, NECK_W), (BODY_L, BODY_W), (0, BODY_W)]
# y-range of the board for grid allocation
YMIN, YMAX = -BODY_W, BODY_W

def mirror_y(y):
    return 2 * CY - y

# ---------------------------------------------------------------- footprints
# pad tuple: (pin, dx, dy, hole, size, shape)   shape: circle | rect | smd (size=(w,h))
def dip_pads_h(n, row_sp, pitch=2.54, hole=0.9, pad=1.6):
    """DIP, long axis horizontal, notch on the LEFT: pin 1 bottom-left, pins 1..n/2 left-to-right
    along the bottom row, n/2+1..n right-to-left along the top row (viewed from the top)."""
    half = n // 2
    span = (half - 1) * pitch
    pads = []
    for i in range(half):
        pads.append((i + 1, -span / 2 + i * pitch, -row_sp / 2, hole, pad, 'rect' if i == 0 else 'circle'))
    for i in range(half):
        pads.append((half + i + 1, span / 2 - i * pitch, row_sp / 2, hole, pad, 'circle'))
    return pads

def soic_pads(n, span, padlen, pitch=1.27, padw=0.6):
    """SOIC, long axis horizontal, pin 1 bottom-left (viewed from the side the part is on)."""
    half = n // 2
    L = (half - 1) * pitch
    pads = []
    for i in range(half):
        pads.append((i + 1, -L / 2 + i * pitch, -span / 2, 0, (padw, padlen), 'smd'))
    for i in range(half):
        pads.append((half + i + 1, L / 2 - i * pitch, span / 2, 0, (padw, padlen), 'smd'))
    return pads

def r0805_pads():
    return [(1, -0.95, 0, 0, (1.0, 1.3), 'smd'), (2, 0.95, 0, 0, (1.0, 1.3), 'smd')]

# ---------------------------------------------------------------- parts (variant U coordinates)
PARTS = {}
def part(ref, pads, x, y, side, body, value, desc, rot=0):
    """rot: 0 or 180 (footprint rotated in its own plane)."""
    PARTS[ref] = dict(ref=ref, pads=pads, x=x, y=y, side=side, body=body, value=value, desc=desc, rot=rot)

# neck: x from BODY_L (48.26) to BOARD_W (74.93). Plug centred at x = BOARD_W - 12.7 (pins span 17.78)
PLUG_X = BOARD_W - 10 * U
part('P1', dip_pads_h(16, 7.62, hole=1.0, pad=1.7), PLUG_X, CY, 'top', (20.3, 9.0),
     'DIP-16 plug', 'Round machined-pin header 2x8 (pins downward), plugs into the U25/U26 socket')
# body: x from 0 to 48.26, y from 0 to 22.86. EEPROM socket on top, rows 15.24 apart, centred y = 11.43
BX = BODY_L / 2
part('U5', dip_pads_h(28, 15.24, hole=1.0, pad=1.7), 19 * U, 9 * U, 'top', (36.5, 15.0),
     'AT28C64B-15PU', 'Font EEPROM in DIP-28 socket (28C64 / 27C64 / 27C256 / 27C512 compatible)')
# logic on the BOTTOM side of the body (viewed from top, mirrored in x by the exporter)
part('U1', soic_pads(20, 9.3, 1.9), 24.0, 9 * U, 'bot', (12.8, 7.5), '74HCT373D', 'Octal transparent latch (address latch), SOIC-20W', rot=180)
part('U2', soic_pads(16, 5.4, 1.5), 12.0, 9 * U, 'bot', (9.9, 3.9), '74HCT161D', '4-bit sync counter (line counter), SOIC-16')
part('U3', soic_pads(16, 5.4, 1.5), 36.0, 9 * U, 'bot', (9.9, 3.9), '74HCT166D', '8-bit PISO shift register (dot shifter), SOIC-16')
part('U4', soic_pads(14, 5.4, 1.5), 49.6, CY, 'bot', (8.6, 3.9), '74HCT125D', 'Quad tri-state buffer (video output), SOIC-14')
# passives, 0805.  Decoupling on the bottom next to the logic; pull-ups on top.
part('C1', r0805_pads(), 3.0, 10.2, 'top', (2.0, 1.25), '100nF', 'decoupling U1', rot=90)
part('C2', r0805_pads(), 5.6, 9 * U, 'bot', (2.0, 1.25), '100nF', 'decoupling U2', rot=90)
part('C3', r0805_pads(), 42.6, 9 * U, 'bot', (2.0, 1.25), '100nF', 'decoupling U3', rot=90)
part('C4', r0805_pads(), 49.6, 1.6, 'bot', (2.0, 1.25), '100nF', 'decoupling U4')
part('C5', r0805_pads(), 3.0, 15.0, 'top', (2.0, 1.25), '100nF', 'decoupling U5', rot=90)
part('R1', r0805_pads(), 3.0, 5.0, 'top', (2.0, 1.25), '1k', 'pull-up U5 pin 1 (VPP / RDY / A15)', rot=90)
part('R2', r0805_pads(), 14.0, 21.7, 'top', (2.0, 1.25), '1k', 'pull-up U5 pin 26 (NC / A13)')
part('R3', r0805_pads(), 8.0, 21.7, 'top', (2.0, 1.25), '1k', 'pull-up U5 pin 27 (/WE / /PGM / A14)')
# (rev B: the two solder jumpers JP1/JP2 that selected the DM8678 / DM86S64 pin assignment are gone;
#  both original chips were measured to use the same assignment - video out on pin 11, enable on
#  pin 12 - so that wiring is now fixed copper: U4 pin 3 -> socket pin 11, U4 pin 1 <- latched pin 12.)

# ---------------------------------------------------------------- nets
NETS = {}
def net(name, *conns):
    NETS.setdefault(name, []).extend(conns)

net('ADR0', ('P1', 3), ('U1', 3))
net('ADR1', ('P1', 2), ('U1', 4))
net('ADR2', ('P1', 1), ('U1', 7))
net('ADR3', ('P1', 15), ('U1', 8))
net('ADR4', ('P1', 14), ('U1', 13))
net('ADR5', ('P1', 13), ('U1', 14))
net('ALC',  ('P1', 4), ('U1', 11))                   # address latch control / strobe -> LE
net('nCLR', ('P1', 5), ('U2', 1))                    # clear -> counter /MR
net('LCLK', ('P1', 6), ('U2', 2))                    # line clock -> counter CP
net('CC',   ('P1', 7), ('U2', 7))                    # clock control -> counter CEP
net('DCLK', ('P1', 9), ('U3', 7))                    # dot clock -> shift register CP
net('nLD',  ('P1', 10), ('U3', 15))                  # load enable -> /PE
net('PIN11', ('P1', 11), ('U4', 3))                 # video out (was JP1 C-A)
net('PIN12', ('P1', 12), ('U1', 17))                 # pin 12 = A7, latched with the address
net('GND',  ('P1', 8), ('U1', 10), ('U2', 8), ('U3', 8), ('U4', 7), ('U5', 14),
    ('C1', 2), ('C2', 2), ('C3', 2), ('C4', 2), ('C5', 2),
    ('U1', 1), ('U1', 18),
    ('U2', 3), ('U2', 4), ('U2', 5), ('U2', 6),
    ('U3', 1), ('U3', 2), ('U3', 6),
    ('U4', 4), ('U4', 5), ('U4', 9), ('U4', 10), ('U4', 12), ('U4', 13),
    ('U5', 20), ('U5', 22), ('U5', 21), ('U5', 23), ('U5', 2))
net('VCC',  ('P1', 16), ('U1', 20), ('U2', 16), ('U3', 16), ('U4', 14), ('U5', 28),
    ('C1', 1), ('C2', 1), ('C3', 1), ('C4', 1), ('C5', 1),
    ('U2', 9), ('U2', 10), ('U3', 9),
    ('R1', 1), ('R2', 1), ('R3', 1))
net('LA0', ('U1', 2), ('U5', 10))
net('LA1', ('U1', 5), ('U5', 9))
net('LA2', ('U1', 6), ('U5', 8))
net('LA3', ('U1', 9), ('U5', 7))
net('LA4', ('U1', 12), ('U5', 6))
net('LA5', ('U1', 15), ('U5', 5))
net('LA7', ('U1', 16), ('U4', 1))                   # latched A7 -> /OE of the output buffer (was JP2 C-A)
net('ROW0', ('U2', 14), ('U5', 4))
net('ROW1', ('U2', 13), ('U5', 3))
net('ROW2', ('U2', 12), ('U5', 25))
net('ROW3', ('U2', 11), ('U5', 24))
net('D0', ('U5', 11), ('U3', 14))
net('D1', ('U5', 12), ('U3', 12))
net('D2', ('U5', 13), ('U3', 11))
net('D3', ('U5', 15), ('U3', 10))
net('D4', ('U5', 16), ('U3', 5))
net('D5', ('U5', 17), ('U3', 4))
net('D6', ('U5', 18), ('U3', 3))
net('PU1', ('U5', 1), ('R1', 2))
net('PU26', ('U5', 26), ('R2', 2))
net('PU27', ('U5', 27), ('R3', 2))
net('SER', ('U3', 13), ('U4', 2))

# ---------------------------------------------------------------- pre-routed bus (top layer, under the EEPROM socket)
# Socket signals run on straight top-layer lanes from the neck to the x of their IC; the router
# only adds the short hops at both ends.  Lanes are ordered so none cross.
NC_PINS = {('U1', 19), ('U2', 15), ('U4', 6), ('U4', 8), ('U4', 11), ('U5', 19)}

def check():
    used = {}
    for n, conns in NETS.items():
        for ref, pin in conns:
            assert ref in PARTS, (n, ref)
            pins = [p[0] for p in PARTS[ref]['pads']]
            assert pin in pins, (n, ref, pin)
            key = (ref, pin)
            assert key not in used, f'{key} in both {used[key]} and {n}'
            used[key] = n
    for ref in ('U1', 'U2', 'U3', 'U4', 'U5', 'P1'):
        for p in PARTS[ref]['pads']:
            if (ref, p[0]) not in used and (ref, p[0]) not in NC_PINS:
                raise AssertionError(f'unconnected {ref} pin {p[0]}')
    return used

# variant-L placement overrides (x, y, rot) for the small top-side parts that sit on the body's
# left strip in variant U (mirroring them would put them into the lane funnel at the neck).
POSE_L = {'R1': (47.5, 12.7, 0), 'C5': (2.5, -3.0, 90), 'C1': (2.5, 5.0, 90),
          'C2': (39.4, -3.2, 0), 'C3': (8.2, 1.27, 90)}

def part_pose(ref, variant):
    """(x, y, rot) of a part in the given variant.  Variant L: body parts are rotated 180 deg as a
    group about the body centre (keeps their relative geometry), neck parts are mirrored in y and
    rotated 180 deg; the plug P1 never moves."""
    p = PARTS[ref]
    x, y, rot = p['x'], p['y'], p['rot']
    if variant == 'L' and ref in POSE_L:
        return POSE_L[ref]
    if variant == 'L' and ref != 'P1':
        y = mirror_y(y)
        if x < 42.0:                  # body part
            x = BODY_L - x
        rot = (rot + 180) % 360
    return x, y, rot

def placed_pads(variant):
    """Absolute pad list for the variant: (ref, pin, x, y, hole, size, shape, layers, net)."""
    import math
    pin2net = check()
    out = []
    for ref, p in PARTS.items():
        px, py, rot = part_pose(ref, variant)
        for (pin, dx, dy, hole, size, shape) in p['pads']:
            a = math.radians(rot)
            rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
            if p['side'] == 'bot':
                ry = -ry            # bottom-side part: mirror about x axis as seen from the top
            layers = ('top', 'bot') if shape != 'smd' else ((p['side'],))
            if shape == 'smd' and rot % 180 == 90:
                size = (size[1], size[0])
            out.append((ref, pin, round(px + rx, 4), round(py + ry, 4), hole, size, shape, layers, pin2net.get((ref, pin))))
    return out

# ---------------------------------------------------------------- bus lanes (computed per variant)
BUS_NETS = ['ADR0', 'ADR1', 'ADR2', 'ADR3', 'ADR4', 'ADR5', 'ALC', 'PIN12', 'nCLR', 'LCLK', 'CC', 'DCLK', 'nLD']
LANE_PITCH = 0.762
LANE_X_END = 43.0
RAILS = {'U': [('VCC', 20.32), ('GND', 1.905)], 'L': [('VCC', mirror_y(20.32)), ('GND', mirror_y(1.905))]}

def lane_y(k, variant):
    y = 5.08 + k * LANE_PITCH
    return y if variant == 'U' else mirror_y(y)

def lane_plan(variant, via_d=0.6, trace_w=0.20, clear=0.25):
    """For every bus net choose lane k and via position so the bottom-layer hop via->pad is legal.
    Returns dict net -> (k, vx, vy, pad_x, pad_y)."""
    import numpy as np
    pads = placed_pads(variant)
    bypin = {(t[0], t[1]): t for t in pads}
    net2dst = {}
    for n in BUS_NETS:
        for (ref, pin) in NETS[n]:
            if ref != 'P1':
                net2dst[n] = bypin[(ref, pin)]
    # obstacle arrays (rect model for every pad; circles approximated by their bounding square)
    ox = np.array([t[2] for t in pads]); oy = np.array([t[3] for t in pads])
    ohw = np.array([t[5][0] / 2 if t[6] == 'smd' else t[5] / 2 for t in pads])
    ohh = np.array([t[5][1] / 2 if t[6] == 'smd' else t[5] / 2 for t in pads])
    onet = np.array([t[8] or '' for t in pads])
    def rect_dist(px, py):      # px, py arrays [S]; returns [S, P]
        dx = np.maximum(np.abs(px[:, None] - ox[None, :]) - ohw[None, :], 0)
        dy = np.maximum(np.abs(py[:, None] - oy[None, :]) - ohh[None, :], 0)
        return np.hypot(dx, dy)
    feas = {}
    for n, dst in net2dst.items():
        px, py = dst[2], dst[3]
        others = onet != n
        opts = []
        for k in range(15):
            vy = lane_y(k, variant)
            if abs(vy - py) < 1.0:
                continue
            for off in (0.0, 0.635, -0.635, 1.27, -1.27, 1.905, -1.905, 2.54, -2.54):
                vx = round(px + off, 4)
                t = np.linspace(0, 1, 30)
                sx, sy = vx + (px - vx) * t, vy + (py - vy) * t
                dd = rect_dist(sx, sy)[:, others]
                if dd.min() < trace_w / 2 + clear:
                    continue
                dv = rect_dist(np.array([vx]), np.array([vy]))[0, others]
                if dv.min() < via_d / 2 + clear:
                    continue
                opts.append((k, vx))
        feas[n] = opts
    # optimal unique lane assignment (Hungarian): cost = hop length, forbidden pairs = large
    from scipy.optimize import linear_sum_assignment
    names = list(net2dst)
    BIG = 1e6
    cost = np.full((len(names), 15), BIG)
    best = {}
    for i, n in enumerate(names):
        px, py = net2dst[n][2], net2dst[n][3]
        for (k, vx) in feas[n]:
            c = abs(lane_y(k, variant) - py) + 0.3 * abs(vx - px)
            if c < cost[i, k]:
                cost[i, k] = c; best[(n, k)] = vx
    rows, cols = linear_sum_assignment(cost)
    plan = {}
    for i, k in zip(rows, cols):
        n = names[i]
        if cost[i, k] >= BIG:
            raise RuntimeError(f'no feasible lane for {n}: ' + str({m: sorted({o[0] for o in feas[m]}) for m in names}))
        px, py = net2dst[n][2], net2dst[n][3]
        plan[n] = (k, best[(n, k)], lane_y(k, variant), px, py)
    return plan

def preroutes(variant):
    """Fixed copper: bus lanes (top) ending at the planned via x, plus VCC/GND rails (top)."""
    plan = lane_plan(variant)
    out = []
    for n, (k, vx, vy, px, py) in plan.items():
        out.append((n, 'top', [(vx, vy), (LANE_X_END, vy)], 0.20))
    return out

def outline(variant):
    if variant == 'U':
        return OUTLINE_U
    return [(x, mirror_y(y)) for (x, y) in OUTLINE_U]

def overlap_check(variant, margin=0.25):
    """Report footprint collisions per layer: every pad box (grown by margin) against every pad box
    and SMD body box of another part on the same layer.  (Through-hole socket bodies sit on the
    top side only; SOIC bodies are checked on the side they are mounted.)"""
    items = []
    for (ref, pin, x, y, hole, size, shape, layers, net) in placed_pads(variant):
        hw, hh = (size[0] / 2, size[1] / 2) if shape == 'smd' else (size / 2, size / 2)
        for L in layers:
            items.append((ref, L, x - hw, y - hh, x + hw, y + hh, 'pad'))
    for ref, p in PARTS.items():
        x, y, rot = part_pose(ref, variant)
        w, h = p['body']
        if rot % 180 == 90: w, h = h, w
        items.append((ref, p['side'], x - w / 2, y - h / 2, x + w / 2, y + h / 2, 'body'))
    bad = set()
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a[0] == b[0] or a[1] != b[1]: continue
            if a[6] == 'body' and b[6] == 'body': continue
            if a[2] < b[4] + margin and b[2] < a[4] + margin and a[3] < b[5] + margin and b[3] < a[5] + margin:
                bad.add((a[0], b[0], a[1]))
    return sorted(bad)

if __name__ == '__main__':
    for v in ('U', 'L'):
        print(v, 'overlaps:', overlap_check(v))
    used = check()
    print(len(PARTS), 'parts', len(NETS), 'nets', len(used), 'connections')
    for v in ('U', 'L'):
        plan = lane_plan(v)
        print(v, {n: (k, round(vx, 2), round(vy, 2)) for n, (k, vx, vy, px, py) in sorted(plan.items(), key=lambda t: t[1][0])})
