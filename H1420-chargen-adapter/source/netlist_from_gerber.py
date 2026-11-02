# Copyright (c) 2026 by The Byte Attic B.V.
"""Final verification from the manufacturing data only.

1. Rebuild the connectivity from the Gerber copper layers + drill file: rasterise F_Cu and B_Cu,
   label connected copper, link the two layers through every plated hole, and partition the
   component pins (pin positions come from the footprints in design.py - geometry only, no nets).
2. Compare the partition with the schematic netlist (design.NETS + NC pins).
3. Simulate the adapter STRUCTURALLY from the reconstructed netlist (no net names, no knowledge
   of which pin is supposed to connect where) against the behavioural models of the original
   DM8678 character generator (rev B hard-wires that pin assignment; the DM86S64 measured identical).

    python3 netlist_from_gerber.py U      (or L)
"""
import sys, random
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from check import parse_gerber, parse_drill, Raster, RES
from design import placed_pads, NETS, NC_PINS, outline
from simulate import DM86S64, DM8678, PIN373, PIN161, PIN166, PIN125, PIN28C64

# ------------------------------------------------------------------ 1. connectivity from copper
def reconstruct(variant, gdir, name):
    pads = [(ref, pin, x, y, shape, layers) for (ref, pin, x, y, hole, size, shape, layers, net) in placed_pads(variant)]
    poly = outline(variant)
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    R = Raster(min(xs), min(ys), max(xs), max(ys))
    cu = {}
    for L, suffix in (('top', 'F_Cu'), ('bot', 'B_Cu')):
        aps, items = parse_gerber(f'{gdir}/{name}-{suffix}.gbr')
        cu[L] = np.array(R.draw_items(aps, items), bool)
    holes = parse_drill(f'{gdir}/{name}-PTH.drl')
    lab = {L: ndimage.label(cu[L], structure=np.ones((3, 3)))[0] for L in cu}
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
        if lab['top'][i, j] and lab['bot'][i, j]:
            union(('top', lab['top'][i, j]), ('bot', lab['bot'][i, j]))
    comp_of = {}
    for (ref, pin, x, y, shape, layers) in pads:
        px, py = R.px(x, y); i, j = int(round(py)), int(round(px))
        labels = [(L, lab[L][i, j]) for L in layers if lab[L][i, j]]
        if not labels:
            print(f'  WARNING: pad {ref}.{pin} has no copper'); continue
        for l in labels[1:]:
            union(labels[0], l)
        comp_of[(ref, pin)] = labels[0]
    groups = {}
    for k, c in comp_of.items():
        groups.setdefault(find(c), set()).add(k)
    return [frozenset(g) for g in groups.values()]

# ------------------------------------------------------------------ 2. compare with the schematic
def compare(groups):
    expected = [frozenset(conns) for conns in NETS.values()] + [frozenset([k]) for k in NC_PINS]
    exp_set = set(expected); got_set = set(groups)
    name_of = {frozenset(c): n for n, c in NETS.items()}
    ok = True
    for g in exp_set - got_set:
        ok = False
        print(f'  MISSING/ALTERED net {name_of.get(g, "NC")}: {sorted(g)}')
    for g in got_set - exp_set:
        ok = False
        print(f'  UNEXPECTED group: {sorted(g)}')
    return ok

# ------------------------------------------------------------------ 3. structural simulation
class Board:
    """Evaluates the adapter from a pin partition only.  Every IC pin is looked up by its
    component (net) id; the IC models are the standard 74HCT373 / 74HCT161 / 28C64 / 74HCT166 /
    74HCT125 functions.  Jumper bridges are given as pairs of jumper pads."""
    def __init__(self, groups, font, bridges):
        self.net = {}
        for gi, g in enumerate(groups):
            for k in g:
                self.net[k] = gi
        # jumper bridges join two components
        alias = {}
        for (a, b) in bridges:
            na, nb = self.net[a], self.net[b]
            for k, n in self.net.items():
                if n == nb: self.net[k] = na
        self.image = {r * 64 + c: font[c][r] & 0x7F for c in range(64) for r in range(16)}
        self.q373 = [0] * 8; self.cnt = 0; self.sr = {k: 0 for k in 'ABCDEFGH'}
        self.p_cp = 0; self.p_clk = 0
        # pull-ups: resistor with one end on VCC pulls the other end
        self.pulled = set()
        vcc = self.net[('P1', 16)]
        for r in ('R1', 'R2', 'R3'):
            a, b = self.net[(r, 1)], self.net[(r, 2)]
            if a == vcc: self.pulled.add(b)
            if b == vcc: self.pulled.add(a)
        self.contention = set()

    def drive(self, val, key, v, tag):
        n = self.net[key]
        if n in val and val[n][1] != tag and val[n][0] != v:
            self.contention.add((tag, val[n][1]))
        val[n] = (v, tag)

    def rd(self, val, key):
        n = self.net[key]
        if n in val: return val[n][0]
        if n in self.pulled: return 1
        return None

    def eval(self, sock):
        """sock: socket pin -> level for the pins the terminal drives.  Returns the level found on
        the P1 output pin nets (dict pin -> level/None)."""
        val = {}
        for p, v in sock.items():
            self.drive(val, ('P1', p), v, 'P1')
        n373 = list(self.q373); ncnt = self.cnt; nsr = dict(self.sr)
        for _ in range(6):                     # settle combinational paths (fixed point)
            before = dict(val)
            # 74HCT373: transparent when LE high, outputs enabled when /OE low
            le = self.rd(val, ('U1', PIN373['LE'])); oe = self.rd(val, ('U1', PIN373['OE']))
            if le:
                n373 = [self.rd(val, ('U1', p)) or 0 for p in PIN373['D']]
            if oe == 0:
                for k, p in enumerate(PIN373['Q']):
                    self.drive(val, ('U1', p), n373[k], 'U1')
            # 74HCT161: async /MR, rising CP with CEP & CET, /PE low = parallel load
            mr = self.rd(val, ('U2', PIN161['MR'])); cp = self.rd(val, ('U2', PIN161['CP']))
            cep = self.rd(val, ('U2', PIN161['CEP'])); cet = self.rd(val, ('U2', PIN161['CET'])); pe = self.rd(val, ('U2', PIN161['PE']))
            if mr == 0:
                ncnt = 0
            elif cp and not self.p_cp:
                if pe == 0:
                    ncnt = sum((self.rd(val, ('U2', p)) or 0) << k for k, p in enumerate(PIN161['P']))
                elif cep and cet:
                    ncnt = (self.cnt + 1) & 15
                else:
                    ncnt = self.cnt
            else:
                ncnt = self.cnt if mr else 0
            for k, p in enumerate(PIN161['Q']):
                self.drive(val, ('U2', p), (ncnt >> k) & 1, 'U2')
            self.drive(val, ('U2', 15), int(ncnt == 15 and bool(cet)), 'U2')
            # 28C64: read when /CE low, /OE low, /WE high
            ce = self.rd(val, ('U5', PIN28C64['CE'])); oe5 = self.rd(val, ('U5', PIN28C64['OE'])); we = self.rd(val, ('U5', PIN28C64['WE']))
            if ce == 0 and oe5 == 0 and we == 1:
                addr = sum((self.rd(val, ('U5', p)) or 0) << k for k, p in enumerate(PIN28C64['A']))
                data = self.image.get(addr & 0x3FF, 0) if addr < 8192 else 0
                if addr >= 1024:               # image only holds the 1 KB font block: A10..A12 must be 0
                    data = 0
                for k, p in enumerate(PIN28C64['D']):
                    self.drive(val, ('U5', p), (data >> k) & 1, 'U5')
            # 74HCT166: /CLR async, CLK gated by INH, SH//LD low = load
            clr = self.rd(val, ('U3', PIN166['CLR'])); inh = self.rd(val, ('U3', PIN166['INH']))
            clk = self.rd(val, ('U3', PIN166['CLK'])); shld = self.rd(val, ('U3', PIN166['SHLD']))
            if clr == 0:
                nsr = {k: 0 for k in 'ABCDEFGH'}
            elif clk and not self.p_clk and not inh:
                if shld == 0:
                    nsr = {name: (self.rd(val, ('U3', p)) or 0) for p, name in PIN166['IN'].items()}
                else:
                    order = 'HGFEDCBA'
                    nsr = {order[i]: self.sr[order[i + 1]] for i in range(7)}
                    nsr['A'] = self.rd(val, ('U3', PIN166['SER'])) or 0
            else:
                nsr = dict(self.sr)
            self.drive(val, ('U3', PIN166['QH']), nsr['H'], 'U3')
            # 74HCT125: four gates (1,2,3 / 4,5,6 / 10,9,8 / 13,12,11)
            for (o, a, y) in ((1, 2, 3), (4, 5, 6), (10, 9, 8), (13, 12, 11)):
                if self.rd(val, ('U4', o)) == 0:
                    self.drive(val, ('U4', y), self.rd(val, ('U4', a)) or 0, f'U4.{y}')
            if val == before:
                break
        # commit sequential state and clock history
        self.q373 = n373; self.cnt = ncnt; self.sr = nsr
        self.p_cp = self.rd(val, ('U2', PIN161['CP'])) or 0
        self.p_clk = self.rd(val, ('U3', PIN166['CLK'])) or 0
        return {p: self.rd(val, ('P1', p)) for p in (11, 12)}

def simulate(groups, mode, seed, cycles=6000):
    rnd = random.Random(seed)
    font = [[rnd.getrandbits(7) for r in range(16)] for c in range(64)]
    if mode == '8678':
        bridges = []                                   # rev B: wired in copper, no jumpers
        ref = DM8678(font); out_pin, in_pin = 11, 12
    else:
        raise ValueError('rev B boards have no DM86S64 jumper position')
    b = Board(groups, font, bridges)
    addr = 0; alc = 1; nclr = 1; lclk = 0; cc = 1; nld = 1; en = 0; dclk = 0
    mism = 0
    for t in range(cycles):
        if rnd.random() < 0.15: addr = rnd.getrandbits(6)
        if rnd.random() < 0.10: alc ^= 1
        if rnd.random() < 0.03: nclr ^= 1
        if rnd.random() < 0.08: lclk ^= 1
        if rnd.random() < 0.05: cc ^= 1
        if rnd.random() < 0.20: nld ^= 1
        if rnd.random() < 0.10: en ^= 1
        dclk ^= 1
        sock = {3: addr & 1, 2: (addr >> 1) & 1, 1: (addr >> 2) & 1, 15: (addr >> 3) & 1, 14: (addr >> 4) & 1, 13: (addr >> 5) & 1,
                4: alc, 5: nclr, 6: lclk, 7: cc, 9: dclk, 10: nld, 8: 0, 16: 1, in_pin: en}
        if mode == '86S64':
            exp = ref.eval(addr, alc, nclr, lclk, cc, dclk, nld, en)
        else:
            exp = ref.eval(addr, en, alc, nclr, lclk, cc, dclk, nld)
        got = b.eval(sock)[out_pin]
        if got != exp:
            mism += 1
            if mism <= 3:
                print(f'    mismatch t={t} mode {mode}: expected {exp} got {got}')
    return mism, sorted(b.contention)

if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else 'U'
    name = f'h1420-chargen-{"U26-upper" if v == "U" else "U25-lower"}'
    groups = reconstruct(v, f'gerber_{v}', name)
    npins = sum(len(g) for g in groups)
    print(f'[{v}] {npins} pins in {len(groups)} copper groups reconstructed from {name} Gerbers')
    ok = compare(groups)
    print(f'[{v}] netlist vs schematic: {"IDENTICAL" if ok else "DIFFERENT"}')
    total = 0; cont = set()
    for mode in ('8678',):
        for seed in range(3):
            m, c = simulate(groups, mode, seed)
            total += m; cont |= set(c)
            print(f'[{v}] structural simulation vs {mode}, seed {seed}: {m} mismatches')
    if cont:
        print(f'[{v}] DRIVER CONTENTION between {cont}')
    print(f'[{v}] RESULT: {"PASS" if ok and total == 0 and not cont else "FAIL"}')
