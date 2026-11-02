# Copyright (c) 2026 by The Byte Attic B.V.
"""Draw the schematic (net-label style) as a PDF with matplotlib."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from design import NETS, PARTS

PIN2NET = {}
for n, conns in NETS.items():
    for ref, pin in conns:
        PIN2NET[(ref, pin)] = n

PINNAMES = {
 'P1': {1: 'A2/A3', 2: 'A1/A2', 3: 'A0/A1', 4: 'ADDR LATCH', 5: '/CLEAR', 6: 'LINE CLOCK', 7: 'CLOCK CTRL', 8: 'GND',
        9: 'DOT CLOCK', 10: '/LOAD', 11: 'OUT|/OE', 12: 'A7|OUT', 13: 'A5/A6', 14: 'A4/A5', 15: 'A3/A4', 16: 'VCC'},
 'U1': {1: '/OE', 2: 'Q0', 3: 'D0', 4: 'D1', 5: 'Q1', 6: 'Q2', 7: 'D2', 8: 'D3', 9: 'Q3', 10: 'GND', 11: 'LE', 12: 'Q4', 13: 'D4', 14: 'D5',
        15: 'Q5', 16: 'Q6', 17: 'D6', 18: 'D7', 19: 'Q7', 20: 'VCC'},
 'U2': {1: '/MR', 2: 'CP', 3: 'D0', 4: 'D1', 5: 'D2', 6: 'D3', 7: 'CEP', 8: 'GND', 9: '/PE', 10: 'CET', 11: 'Q3', 12: 'Q2', 13: 'Q1', 14: 'Q0', 15: 'TC', 16: 'VCC'},
 'U3': {1: 'SER', 2: 'A', 3: 'B', 4: 'C', 5: 'D', 6: 'CLK INH', 7: 'CLK', 8: 'GND', 9: '/CLR', 10: 'E', 11: 'F', 12: 'G', 13: 'QH', 14: 'H', 15: 'SH//LD', 16: 'VCC'},
 'U4': {1: '/1OE', 2: '1A', 3: '1Y', 4: '/2OE', 5: '2A', 6: '2Y', 7: 'GND', 8: '3Y', 9: '3A', 10: '/3OE', 11: '4Y', 12: '4A', 13: '/4OE', 14: 'VCC'},
 'U5': {1: 'VPP/RDY/A15', 2: 'A12', 3: 'A7', 4: 'A6', 5: 'A5', 6: 'A4', 7: 'A3', 8: 'A2', 9: 'A1', 10: 'A0', 11: 'D0', 12: 'D1', 13: 'D2', 14: 'GND',
        15: 'D3', 16: 'D4', 17: 'D5', 18: 'D6', 19: 'D7', 20: '/CE', 21: 'A10', 22: '/OE', 23: 'A11', 24: 'A9', 25: 'A8', 26: 'NC/A13', 27: '/WE//PGM/A14', 28: 'VCC'},
}
TITLES = {'P1': 'P1  plug into DM8678 / DM86S64 socket (U25 / U26)', 'U1': 'U1  74HCT373  address latch', 'U2': 'U2  74HCT161  line counter',
          'U3': 'U3  74HCT166  dot shift register', 'U4': 'U4  74HCT125  tri-state output', 'U5': 'U5  AT28C64B  font EEPROM (DIP-28 socket)'}

def draw_ic(ax, ref, x, y, w, pins_left, pins_right, pitch=0.42):
    n = max(len(pins_left), len(pins_right))
    h = (n + 1) * pitch
    ax.add_patch(Rectangle((x, y - h), w, h, fill=False, lw=1.2))
    ax.text(x + w / 2, y + 0.15, TITLES.get(ref, ref), ha='center', va='bottom', fontsize=8.5, weight='bold')
    for k, p in enumerate(pins_left):
        py = y - (k + 1) * pitch
        ax.plot([x - 0.9, x], [py, py], 'k', lw=0.9)
        ax.text(x + 0.08, py, f'{p} {PINNAMES[ref].get(p, "")}', ha='left', va='center', fontsize=6.5)
        net = PIN2NET.get((ref, p), 'NC')
        ax.text(x - 1.0, py, net, ha='right', va='center', fontsize=7, color='#1a5276' if net not in ('GND', 'VCC') else '#7b241c')
    for k, p in enumerate(pins_right):
        py = y - (k + 1) * pitch
        ax.plot([x + w, x + w + 0.9], [py, py], 'k', lw=0.9)
        ax.text(x + w - 0.08, py, f'{PINNAMES[ref].get(p, "")} {p}', ha='right', va='center', fontsize=6.5)
        net = PIN2NET.get((ref, p), 'NC')
        ax.text(x + w + 1.0, py, net, ha='left', va='center', fontsize=7, color='#1a5276' if net not in ('GND', 'VCC') else '#7b241c')
    return h

def main(out='schematic.pdf'):
    fig = plt.figure(figsize=(16.5, 11.7))   # A3 landscape
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 42); ax.set_ylim(0, 29.7); ax.axis('off')
    ax.text(21, 28.9, 'Hazeltine 1420 character-generator adapter, rev B (replaces DM8678 / DM86S64 at U25 / U26)', ha='center', fontsize=14, weight='bold')
    ax.text(21, 28.3, 'net-label schematic: pins carrying the same label are connected. Two board variants (U26 upper / U25 lower) share this circuit.',
            ha='center', fontsize=9)
    # column 1: plug
    draw_ic(ax, 'P1', 2.6, 27.0, 5.6, [1, 2, 3, 4, 5, 6, 7, 8], [16, 15, 14, 13, 12, 11, 10, 9])
    ax.text(2.6, 22.7, 'pin 11 = video OUT, pin 12 = A7 / enable, active low', fontsize=6.5)
    ax.text(2.6, 22.3, '(same on both chips, measured)', fontsize=6.5)
    # column 2: latch + counter
    draw_ic(ax, 'U1', 11.8, 27.0, 3.2, [3, 4, 7, 8, 13, 14, 17, 18, 11, 1, 10], [2, 5, 6, 9, 12, 15, 16, 19, 20])
    draw_ic(ax, 'U2', 11.8, 20.6, 3.2, [2, 1, 7, 10, 9, 3, 4, 5, 6, 8], [14, 13, 12, 11, 15, 16])
    # column 3: EEPROM
    draw_ic(ax, 'U5', 20.4, 27.0, 3.6, [10, 9, 8, 7, 6, 5, 4, 3, 25, 24, 21, 23, 2, 20, 22, 14], [11, 12, 13, 15, 16, 17, 18, 19, 1, 26, 27, 28])
    # column 4: shift register + buffer
    draw_ic(ax, 'U3', 29.6, 27.0, 3.4, [14, 12, 11, 10, 5, 4, 3, 2, 1, 7, 15, 6, 9, 8], [13, 16])
    draw_ic(ax, 'U4', 29.6, 19.0, 3.4, [2, 1, 5, 4, 9, 10, 12, 13, 7], [3, 6, 8, 11, 14])
    # passives and jumpers text block
    txt = [
        'R1, R2, R3  1 kOhm 0805   VCC -> U5 pin 1, 26, 27  (nets PU1, PU26, PU27): keep /WE high on a 28C64,',
        '            set A13/A14/A15 high on a 27C256/27C512 (image block replicated, see build_eeprom.py)',
        'C1..C5      100 nF 0805 decoupling, one per IC (VCC-GND)',
        '',
        'Rev B: no jumpers.  Video out U4 pin 3 -> socket pin 11 (net PIN11); latched socket pin 12 (A7) -> U4 pin 1 /OE (net LA7).',
        '        (Rev A had solder jumpers JP1/JP2 for a DM86S64 pin assignment that turned out to be the same as the DM8678 one;',
        '         rev A boards are used with JP1 C-A and JP2 C-A bridged, which is exactly this wiring.)',
        '',
        'Output enable polarity: U4 = 74HCT125 -> output active when latched pin 12 is LOW, as measured on both original chips.',
        'If the font dump of a chip shows it outputs when pin 12 is HIGH, fit a 74HCT126 instead (same pinout, active-high enable).',
        '',
        'Logic family: 74HCT (TTL-compatible inputs, VIH = 2.0 V).  The terminal drives the socket with 74LS outputs (VOH >= 2.7 V),',
        'which plain 74HC (VIH = 3.5 V) would not reliably read.  Do not substitute 74HC for U1-U4.',
        '',
        'Timing: address -> latch (74HCT373, ~25 ns) -> EEPROM (150 ns) -> 74HC166 setup: ~190 ns < 280 ns spec of the',
        'original (t_S2).  Dot clock up to 25 MHz with 74HCT166; Hazeltine 1420 dot clock is below 20 MHz.',
        '',
        'Row address: the 74HC161 replaces the on-chip mod-16 line counter (CP = line clock, CEP = clock control,',
        '/MR = /clear).  Descender shifting of the original is baked into the EEPROM image row by row.',
        'Shift register: /LOAD -> SH//LD; DOT CLOCK -> CLK; EEPROM D0 (first dot) -> H ... D6 -> B; A and SER = 0,',
        'so the output goes low after the 7 dots exactly like the original.',
    ]
    for k, t in enumerate(txt):
        ax.text(1.0, 12.6 - k * 0.5, t, fontsize=7.8, family='monospace', va='top')
    ax.text(41.5, 0.4, 'Copyright (c) 2026 by The Byte Attic B.V.', ha='right', va='bottom', fontsize=8)
    fig.savefig(out)
    print('wrote', out)

if __name__ == '__main__':
    main()
