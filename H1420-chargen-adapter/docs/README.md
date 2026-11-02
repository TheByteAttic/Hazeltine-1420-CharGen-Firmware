# Docs

`verification-report.txt` is the raw output of the final checks run on the revision B manufacturing
files in `../hardware/gerbers/`, for both boards:

* `netlist_from_gerber.py`: pins partitioned into nets from the Gerber copper and drill data alone,
  compared with the schematic netlist (IDENTICAL, 126 pins in 44 nets), then the reconstructed netlist
  simulated against the DM8678 behavioural model for 3 x 6000 random cycles (0 mismatches, no
  driver contention).
* `drc.py`: JLCPCB 2-layer design rules measured on the rasterised Gerbers, every rule listed with the
  measured value and the limit (PASS on both boards).

The reference manual of the terminal (Hazeltine HI-1079, "1420 Video Display Terminal Reference
Manual", 1979) is on bitsavers.org under pdf/hazeltine/Hazeltine_1420/; the DM8678 and DM86S64 data
sheets are in National Semiconductor's 1980-81 data books, also on bitsavers.
