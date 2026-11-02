# KiCad boards

`h1420-chargen-U26-upper.kicad_pcb` and `h1420-chargen-U25-lower.kicad_pcb` are the same two layouts
as the Gerbers, as editable KiCad 8 board files. Footprints are embedded, so no library is needed;
there is no schematic project behind them (the design lives in `../../source/design.py`), so KiCad
will show the nets but cannot run a schematic/PCB comparison.

Open the board, press **B** to refill the ground zone, then plot if you want your own Gerbers.
Teardrops are plain copper polygons. The files were written by `../../source/export.py`; the
Gerbers in `../gerbers/` are the reference manufacturing data, not a KiCad plot.
