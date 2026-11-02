# chargen_dump

Arduino sketch that reads the font out of a National DM8678 or DM86S64 character generator.
It drives the chip's address, row and dot clocks itself, so the chip can be read on a breadboard,
outside the terminal. Wiring, `CHIP` selection and serial settings are at the top of the sketch;
usage is described in `../README.md`.
