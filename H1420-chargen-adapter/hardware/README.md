# Hardware

Manufacturing data for the two adapter boards (revision B).

| File / folder | What it is |
|---------------|-----------|
| `gerbers/` | Gerber + drill zips, one per board, ready to upload to JLCPCB |
| `kicad/` | the same boards as editable KiCad 8 files |
| `schematic.pdf` | net-label schematic of the circuit (shared by both boards) |
| `bom.csv` | bill of materials for one adapter (order two of everything) |
| `images/` | renders of both boards, single-layer track views, layout previews |

## Board facts

* 2 layers, 1.6 mm FR-4, 0.20 mm signal traces (0.40 mm power), 0.6/0.3 mm vias, bottom-side ground pour
  with thermal reliefs, teardrops on every pad and via, 45-degree geometry only.
* Size: 74.9 x 24.1 mm overall; the 14 x 29 mm "neck" plugs into the DIP-16 socket, the body extends to
  the left of the socket about 10 mm above the terminal's board.
* Logic (U1-U4) and decoupling on the bottom side; EEPROM socket, pull-ups and the plug pins on top.
* The plug: two 8-pin strips of round machined (turned) pins, 2.54 mm pitch, rows 7.62 mm apart, in
  1.0 mm plated holes, pin 1 = square pad at the socket's notch end.
* Design-rule check against JLCPCB's 2-layer capability: PASS on both boards (`../docs/verification-report.txt`).

## U26-upper vs U25-lower

Same circuit, mirror-image outline. `U26-upper` bends upward (away from U25), `U25-lower` bends downward
(away from U26). Order 5 of each (JLCPCB minimum); you need one of each.
