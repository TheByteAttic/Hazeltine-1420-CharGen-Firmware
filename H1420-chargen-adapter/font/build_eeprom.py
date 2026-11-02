#!/usr/bin/env python3
# Copyright (c) 2026 by The Byte Attic B.V.
"""
build_eeprom.py - turn a chargen_dump.ino capture into the EEPROM image for the adapter.

    python3 build_eeprom.py capture.txt font.bin [--size 8192]

Image layout (matches the adapter wiring):
    EEPROM address = row * 64 + character        (A0..A5 = character code, A6..A9 = line counter)
    data bit n     = dot n of that row, bit 0 = first dot shifted out (leftmost on screen)
    bit 7          = always 0 (the 8th shift clock of the original outputs a 0)
The 1 KB block is replicated through the whole image so the same file works for a 28C64
(A10-A12 grounded, block at 0x0000) and for a 27C256 / 27C512 (A13-A15 pulled high by
R1-R3, block at 0x6000 / 0xE000).
"""
import re, sys

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    size = 8192
    for a in sys.argv[1:]:
        if a.startswith('--size'):
            size = int(a.split('=')[1]) if '=' in a else int(sys.argv[sys.argv.index(a) + 1])
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    src, dst = args[0], args[1]
    block = bytearray(1024)
    seen = set()
    for line in open(src, errors='replace'):
        m = re.match(r'\s*C\s+0x([0-9A-Fa-f]{2})\s*:\s*((?:[0-9A-Fa-f]{2}\s*){16})', line)
        if not m:
            continue
        c = int(m.group(1), 16)
        rows = [int(h, 16) for h in m.group(2).split()]
        for r, v in enumerate(rows):
            block[r * 64 + c] = v & 0x7F
        seen.add(c)
    missing = sorted(set(range(64)) - seen)
    if missing:
        print(f'WARNING: no data for characters {missing}')
    img = bytearray(size)
    for off in range(0, size, 1024):
        img[off:off + 1024] = block
    open(dst, 'wb').write(img)
    print(f'wrote {dst}: {size} bytes, {len(seen)} characters, block replicated {size // 1024} times')
    # preview
    for c in sorted(seen)[:4]:
        print(f'char 0x{c:02X}:')
        for r in range(12):
            v = block[r * 64 + c]
            print('   ' + ''.join('#' if (v >> b) & 1 else '.' for b in range(7)))

if __name__ == '__main__':
    main()
