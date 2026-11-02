# Source

The boards were not drawn in a CAD package; they were generated and verified by the Python in
this directory. You do not need any of it to build the adapters (use `../hardware/`), but it is
what makes the design reproducible and checkable.

| File | Role |
|------|------|
| `design.py` | the design: outline, footprints, part placement, netlist, bus-lane plan for both variants |
| `router2.py`, `route2.py` | negotiated-congestion (PathFinder) router and its driver; produces `layout_U.json` / `layout_L.json` |
| `pour.py` | bottom-layer ground pour (polygon, pinch removal, thermal reliefs) |
| `cleanup.py` | geometric clean-up of the routed tracks: 45-degree geometry, stub removal, teardrops |
| `dejumper.py` | revision B: removes the rev A solder jumpers from the routed layouts without re-routing (see below) |
| `export.py` | Gerber (RS-274X) + Excellon + KiCad export, including silkscreen with collision-checked labels |
| `drc.py` | design-rule check of the Gerbers against JLCPCB 2-layer rules (rasterised) |
| `check.py` | independent short / open / clearance check of the Gerbers against the layout |
| `netlist_from_gerber.py` | rebuilds the netlist from the Gerber copper + drill alone, compares it with the schematic, and simulates the result structurally against the DM8678 model |
| `simulate.py` | behavioural models of the DM86S64 and the DM8678 (from their datasheets) and of the adapter, random-cycle comparison |
| `render.py`, `preview.py`, `schematic.py` | the images in `../hardware/images/` and `../hardware/schematic.pdf` |
| `board.py` | board geometry model (pads, outline, clearances) shared by the router and the exporter; also contains the first-generation grid router, superseded by `router2.py` |
| `layout_U.json`, `layout_L.json` | the routed layouts (rev B) that `export.py` turns into Gerbers |

Requirements: Python 3, numpy, scipy, Pillow, matplotlib.

## Reproducing the manufacturing files

    python3 export.py U          # writes gerber_U/, h1420-chargen-U26-upper-gerbers.zip, .kicad_pcb
    python3 export.py L
    python3 drc.py U             # JLCPCB rules, PASS/FAIL per rule  (a few minutes each)
    python3 check.py U
    python3 netlist_from_gerber.py U

Re-routing from scratch (`route2.py U`, then `cleanup.py U`) gives a functionally identical but not
geometrically identical board; the layouts in this directory are the ones that were manufactured.

## Revision B

Rev A had two solder jumpers (JP1/JP2) that selected between the DM8678 and the DM86S64 pin
assignment. Both chips turned out to use the same one. `dejumper.py` converts the routed rev A layout
into rev B by deleting the six jumper pads, turning the two bridges into 0.20 mm tracks between the
same points, removing the one dangling branch that served the unused option, and regenerating
teardrops and pour; it asserts that nothing else changed. The rev A layouts are not kept here; rev B is
what is manufactured and what the verification report describes.
