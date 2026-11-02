# Copyright (c) 2026 by The Byte Attic B.V.
"""Functional verification: build the adapter from the NETLIST (design.NETS, pin numbers) using
behavioural models of the 74x373 / 74x161 / EEPROM / 74x166 / 74x125, drive it with the
socket signals, and compare the serial video output cycle by cycle with a behavioural model
of the DM86S64 (datasheet 8-15..8-20) for both jumper positions.

Runs a randomised test: random font, random character streams, random line-clock / clear /
clock-control / address-latch / load / output-enable activity."""
import random
from design import NETS, check

pin2net = check()
def N(ref, pin):
    return pin2net.get((ref, pin))

# ---------------------------------------------------------------- reference model (DM86S64)
class DM86S64:
    def __init__(self, font):           # font[char][row] -> 7-bit int, bit0 = first dot out
        self.font = font
        self.latch = 0; self.counter = 0; self.sr = 0; self.out = 0
        self.prev_dot = 0; self.prev_line = 0
    def eval(self, addr, alc, nclr, lclk, cc, dclk, nld, noe):
        # address latch: transparent when alc high
        if alc: self.latch = addr & 63
        # counter: async clear, rising line clock when cc high
        if not nclr: self.counter = 0
        elif lclk and not self.prev_line and cc: self.counter = (self.counter + 1) & 15
        self.prev_line = lclk
        # shift register on rising dot clock
        if dclk and not self.prev_dot:
            if not nld:
                self.sr = self.font[self.latch][self.counter] & 0x7F   # 7 bits, bit0 = first out
            else:
                self.sr >>= 1                                          # zeros shift in
        self.prev_dot = dclk
        q = self.sr & 1
        return None if noe else q                                     # None = Hi-Z

class DM8678:
    """Independent model of the DM8678 from its logic diagram (datasheet p.7-117/118): seven address
    latches A1..A7 controlled by STROBE (low = hold), 1-of-64 decoder on A1..A6, 4-bit line counter
    with async /CLEAR, LINE RATE CLOCK and CLOCK CONTROL, 7-bit P.I.S.O. register with synchronous
    /LOAD on DOT RATE CLOCK, and a TRI-STATE output gated by the latched A7 (enabled when A7 = 0)."""
    def __init__(self, font):
        self.font = font
        self.lat = [0] * 7; self.cnt = 0; self.sr = [0] * 7
        self.p_dot = 0; self.p_line = 0
    def eval(self, a1_a6, a7, strobe, nclr, lclk, cc, dclk, nld):
        if strobe:                                    # fall-through while high
            self.lat = [(a1_a6 >> k) & 1 for k in range(6)] + [a7]
        if not nclr: self.cnt = 0
        elif lclk and not self.p_line and cc: self.cnt = (self.cnt + 1) & 15
        self.p_line = lclk
        if dclk and not self.p_dot:
            if not nld:
                code = sum(b << k for k, b in enumerate(self.lat[:6]))
                row = self.font[code][self.cnt] & 0x7F
                self.sr = [(row >> k) & 1 for k in range(7)]   # sr[0] = first dot out
            else:
                self.sr = self.sr[1:] + [0]
        self.p_dot = dclk
        return None if self.lat[6] else self.sr[0]

# ---------------------------------------------------------------- adapter built from the netlist
PIN373 = {'OE': 1, 'LE': 11, 'D': [3, 4, 7, 8, 13, 14, 17, 18], 'Q': [2, 5, 6, 9, 12, 15, 16, 19]}
PIN161 = {'MR': 1, 'CP': 2, 'P': [3, 4, 5, 6], 'CEP': 7, 'PE': 9, 'CET': 10, 'Q': [14, 13, 12, 11]}
PIN166 = {'SER': 1, 'IN': {2: 'A', 3: 'B', 4: 'C', 5: 'D', 10: 'E', 11: 'F', 12: 'G', 14: 'H'}, 'INH': 6, 'CLK': 7, 'CLR': 9, 'QH': 13, 'SHLD': 15}
PIN125 = {'OE': 1, 'A': 2, 'Y': 3}
PIN28C64 = {'A': [10, 9, 8, 7, 6, 5, 4, 3, 25, 24, 21, 23, 2], 'D': [11, 12, 13, 15, 16, 17, 18, 19], 'CE': 20, 'OE': 22, 'WE': 27}

class Adapter:
    def __init__(self, font, mode):
        self.image = {}
        for c in range(64):
            for r in range(16):
                self.image[r * 64 + c] = font[c][r] & 0x7F
        self.mode = mode                      # '8678' or '86S64' (jumper positions)
        self.q373 = [0] * 8; self.cnt = 0; self.sr = {k: 0 for k in 'ABCDEFGH'}
        self.prev_cp = 0; self.prev_clk = 0
    def eval(self, sock):
        """sock: dict socket-pin -> level (1..16), pins 11/12 per mode.  Returns output or None."""
        net = {}
        for p, v in sock.items():
            net[N('P1', p)] = v
        # jumper bridges
        if self.mode == '8678':      # JP1 C-A: VOUT->PIN11 ; JP2 C-A: nOE<-LA7
            oe_src = 'LA7'; out_pin = 11
        else:                        # JP1 C-B: VOUT->PIN12 ; JP2 C-B: nOE<-PIN11
            oe_src = 'PIN11'; out_pin = 12
        # 74x373: transparent when LE high, /OE low
        assert N('U1', PIN373['OE']) == 'GND'
        le = net[N('U1', PIN373['LE'])]
        d = [0 if N('U1', p) == 'GND' else net[N('U1', p)] for p in PIN373['D']]
        if le: self.q373 = d
        for k, p in enumerate(PIN373['Q']):
            if N('U1', p): net[N('U1', p)] = self.q373[k]
        # 74x161
        assert N('U2', PIN161['PE']) == 'VCC' and N('U2', PIN161['CET']) == 'VCC'
        mr = net[N('U2', PIN161['MR'])]; cp = net[N('U2', PIN161['CP'])]; cep = net[N('U2', PIN161['CEP'])]
        if not mr: self.cnt = 0
        elif cp and not self.prev_cp and cep: self.cnt = (self.cnt + 1) & 15
        self.prev_cp = cp
        for k, p in enumerate(PIN161['Q']):
            net[N('U2', p)] = (self.cnt >> k) & 1
        # EEPROM (CE, OE grounded, WE pulled up)
        assert N('U5', PIN28C64['CE']) == 'GND' and N('U5', PIN28C64['OE']) == 'GND' and N('U5', PIN28C64['WE']) == 'PU27'
        addr = 0
        for k, p in enumerate(PIN28C64['A']):
            n = N('U5', p)
            bit = 0 if n == 'GND' else net[n]
            addr |= bit << k
        data = self.image.get(addr, 0)
        for k, p in enumerate(PIN28C64['D']):
            n = N('U5', p)
            if n: net[n] = (data >> k) & 1
        # 74x166
        assert N('U3', PIN166['CLR']) == 'VCC' and N('U3', PIN166['INH']) == 'GND' and N('U3', PIN166['SER']) == 'GND'
        clk = net[N('U3', PIN166['CLK'])]; shld = net[N('U3', PIN166['SHLD'])]
        if clk and not self.prev_clk:
            if not shld:
                for p, name in PIN166['IN'].items():
                    n = N('U3', p)
                    self.sr[name] = 0 if n == 'GND' else net[n]
            else:
                order = 'HGFEDCBA'
                for i in range(7):
                    self.sr[order[i]] = self.sr[order[i + 1]]
                self.sr['A'] = 0    # SER = GND
        self.prev_clk = clk
        net[N('U3', PIN166['QH'])] = self.sr['H']
        # 74x125 gate 1
        assert N('U4', PIN125['A']) == 'SER' and N('U4', PIN125['Y']) == 'VOUT' and N('U4', PIN125['OE']) == 'nOE'
        noe = net[oe_src]
        y = None if noe else net['SER']
        # output pin check
        assert (out_pin == 11 and self.mode == '8678') or (out_pin == 12 and self.mode == '86S64')
        return y

# ---------------------------------------------------------------- random test
def run(seed, mode, cycles=6000):
    rnd = random.Random(seed)
    font = [[rnd.getrandbits(7) for r in range(16)] for c in range(64)]
    ref = DM86S64(font) if mode == '86S64' else DM8678(font); dut = Adapter(font, mode)
    addr = 0; alc = 1; nclr = 1; lclk = 0; cc = 1; nld = 1; noe = 0; a7 = 0
    dclk = 0; mism = 0; checked = 0
    for t in range(cycles):
        # slow signals change occasionally
        if rnd.random() < 0.15: addr = rnd.getrandbits(6)
        if rnd.random() < 0.10: alc ^= 1
        if rnd.random() < 0.03: nclr ^= 1
        if rnd.random() < 0.08: lclk ^= 1
        if rnd.random() < 0.05: cc ^= 1
        if rnd.random() < 0.20: nld ^= 1
        if rnd.random() < 0.10: noe ^= 1
        dclk ^= 1
        sock = {3: addr & 1, 2: (addr >> 1) & 1, 1: (addr >> 2) & 1, 15: (addr >> 3) & 1, 14: (addr >> 4) & 1, 13: (addr >> 5) & 1,
                4: alc, 5: nclr, 6: lclk, 7: cc, 9: dclk, 10: nld, 8: 0, 16: 1}
        if mode == '86S64':
            sock[11] = noe; sock[12] = 0          # pin 12 is our own output; value irrelevant
            exp = ref.eval(addr, alc, nclr, lclk, cc, dclk, nld, noe)
        else:
            # DM8678: A7 on pin 12 (latched with the address by STROBE = pin 4); pin 11 is our output
            sock[12] = noe; sock[11] = 0
            exp = ref.eval(addr, noe, alc, nclr, lclk, cc, dclk, nld)
        got = dut.eval(sock)
        checked += 1
        if got != exp:
            mism += 1
            if mism <= 5:
                print(f'  mismatch t={t}: expected {exp} got {got} (mode {mode})')
    return mism, checked

if __name__ == '__main__':
    total = 0
    for mode in ('86S64', '8678'):
        for seed in range(5):
            m, n = run(seed, mode)
            total += m
            print(f'mode {mode:6s} seed {seed}: {n} cycles, {m} mismatches')
    print('RESULT:', 'PASS' if total == 0 else f'FAIL ({total} mismatches)')
