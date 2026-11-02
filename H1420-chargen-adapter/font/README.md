# Fonts

Everything about the contents of the EEPROM: how to read the original chips, the dumps of one
Hazeltine 1420, and the images to program.

| File | What it is |
|------|-----------|
| `chargen_dump/chargen_dump.ino` | Arduino (Uno) sketch that reads all 64 characters out of a DM8678 or DM86S64 and prints them as hex plus an ASCII-art preview |
| `build_eeprom.py` | turns a saved sketch output into an 8 KB EEPROM image |
| `DM8678CRCN-U25-lower.txt`, `DM86S64CQSN-U26-upper.txt` | the dumps of the two chips of the author's terminal (1979 board); the name says which socket the chip came from and therefore which adapter its image goes into |
| `DM8678CRCN-U25-lower.bin`, `DM86S64CQSN-U26-upper.bin` | the corresponding 8 KB images, built from those dumps; these exact files are programmed in the adapters running in that terminal (MD5 231de80c2e8784e09f140c8cebcfadbb and 40188b98869d7289d5711c0c63447291) |

## Which chip holds what

* **DM8678CRCN**: codes 0x00-0x1F are the control-symbol glyphs, codes 0x20-0x3F are ASCII 0x60-0x7F
  (lower case and the symbols around it).
* **DM86S64CQSN**: ASCII 0x20-0x5F (space, punctuation, digits, capitals); chip code = ASCII - 0x40 mod 64.

In the author's terminal the DM86S64 sits in U26 (upper socket) and the DM8678 in U25 (lower socket), so
`DM86S64CQSN-U26-upper.bin` goes into the U26-upper adapter and `DM8678CRCN-U25-lower.bin` into the
U25-lower adapter. Check your own board before assuming the same.

The terminal selects the chip with socket pin 12 (A7); both chips were measured to output on pin 11 and
to be enabled with pin 12 low.

## Image layout

EEPROM address = row x 64 + character code; one byte per scan line, bit 0 = first dot out, 7 bits used,
16 rows per character (rows 10-15 blank in this font). The 1 KB block is replicated eight times through
the 8 KB so the same file also works in a 27C64, 27C256 or 27C512 (the adapter pulls the upper address
lines high).

## Dumping your own chips

Do this first, while the originals still work; a font dumped from your own chips is better than
somebody else's, and later terminals may have a different one.

1. Put the chip on a breadboard and wire it to a 5 V Arduino Uno exactly as listed at the top of
   `chargen_dump.ino` (address bits 0-5 on D2, D3, D4, A0, A1, A2; data/control pins 4-7 and 9-12 on
   D5-D12; pin 8 to GND, pin 16 to 5 V). The chip draws up to 140 mA; the Uno's 5 V pin is fine.
2. Set `CHIP` in the sketch to `CHIP_DM8678` or `CHIP_DM86S64` and upload. Serial monitor at 115200 baud.
3. The sketch first tries both levels on the enable pin and reports how many lit dots it saw with each,
   then dumps all 64 characters (16 row bytes each) followed by an ASCII-art preview. Save the whole
   output to a text file. If the serial monitor drops characters, re-run; the hex lines must be complete.
4. `python3 build_eeprom.py yourdump.txt yourdump.bin` writes the 8 KB image and prints the previews
   again from the parsed data, so you can check them against the originals.

## Programming

Any programmer that handles the AT28C64B: select exactly that device (not a generic 28C64), program,
then remove the chip, reinsert it and read it back against the .bin file. A chip that verifies in the
programmer but reads 0xFF afterwards shows up in the terminal as solid blocks for every character of
that set.
