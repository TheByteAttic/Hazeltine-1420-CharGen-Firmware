# Docs

| File | What it is |
|------|-----------|
| `verification-report.txt` | raw output of the final checks on the rev B manufacturing files (see below) |
| `DM8678 Datasheet.pdf` | National Semiconductor DM8678 character generator data sheet |
| `DM86S64 1980_Memory_Data_Book.pdf` | the DM86S64 pages from National's 1980 Memory Data Book |

`verification-report.txt` is the raw output of the final checks run on the revision B manufacturing
files in `../hardware/gerbers/`, for both boards:

* `netlist_from_gerber.py`: pins partitioned into nets from the Gerber copper and drill data alone,
  compared with the schematic netlist (IDENTICAL, 126 pins in 44 nets), then the reconstructed netlist
  simulated against the DM8678 behavioural model for 3 x 6000 random cycles (0 mismatches, no
  driver contention).
* `drc.py`: JLCPCB 2-layer design rules measured on the rasterised Gerbers, every rule listed with the
  measured value and the limit (PASS on both boards).

The terminal's reference manual (Hazeltine HI-1079, 1979) and its firmware are in
`../../H1420-Bitsavers-firmware/`.
