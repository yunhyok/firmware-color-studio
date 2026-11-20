# PENTAX Q7 camera pack: research log and hand-over

Goal: add **PENTAX Q7** as a second, selectable camera in Firmware Color Studio, with DCP recipes
derived from its firmware in the same way as the K-3 Mark III pack. This file is the working
record. It is updated at every milestone so that the work can be resumed from here.

**Status: in progress (research phase). The firmware is unpacked and symbolised, the colour tables are exported, and the colour matrix and gamma routines are ported to Python and reproduce the emulated firmware exactly (see "Colour arithmetic"). Reversal Film gamma, factory settings per Custom Image and the app work are still to do. Nothing in the app has changed yet.**

## How to resume

1. Read "Findings" and "Next steps" below. Each finding states how it was obtained.
   Earlier research on this firmware is in
   [pentax-q7-firmware-analysis](https://github.com/yunhyok/pentax-q7-firmware-analysis)
   (file structure, unpacking, update path, colour matrix routing, HDR). The K-3 III engine this
   work is compared with is in
   [pentax-k3iii-firmware-analysis](https://github.com/yunhyok/pentax-k3iii-firmware-analysis).
   New findings from here are also sent to the Q7 repository
   ([pentax-q7-firmware-analysis pull request 3](https://github.com/yunhyok/pentax-q7-firmware-analysis/pull/3)).
2. The firmware is not in the repository and must not be committed (`*.bin` is ignored).
   Input used: `fwdc603p.bin`, 18,743,520 bytes,
   SHA-256 `8a928b574623c28624127501526d8496a98a42eac3d843def6d3b5ceb074ff3b`.
3. The scripts in `tools/q7/` take the firmware path as their first argument and only read it:
   `python3 -I tools/q7/<script>.py /path/to/fwdc603p.bin`. `disasm.py`, `emu.py` and `check_port.py`
   need `capstone` and `unicorn` (not project dependencies; install them in a scratch environment).
4. Work on branch `claude/affectionate-archimedes-wg148l`; the draft pull request for this work
   links to this file.

## Findings

### Container and platform (verified by `tools/q7/look.py`, `arch.py`, `strs.py`, `layout.py`)

- The file is **not encrypted**. It is not the Ricoh/Pentax LZ container that the K-3 III
  decoder (`inspect_firmware.py` in the research repository) reads.
- Trailer: `ORION`, `KB538`, `77690` at `0x11e00c0`.
- Platform: **Zoran COACH** (strings `Zburn/...`, `Os/Gpio/GpioC10.c`, `CFIPB_C12_*`), ThreadX RTOS
  (`Os/Rtos/Tx/*.c`), **MIPS little-endian** (6,285 `jr ra`, 3,260 `addiu sp,sp,-N`, none big-endian).
  Register scripts at the start address `0xb8002000` (MIPS KSEG1).
- Rough layout by entropy per 256 KiB and by what the strings show:

  | File offset | Content |
  |---|---|
  | `0x000000`–`0x240000` | plain MIPS code and strings (burner, OS, boot) |
  | `0x240000`–`0x780000` | high entropy (7.7 bit/byte): compressed or packed, **not yet identified** |
  | `0x780000`–`0xa40000` | low entropy; contains FAT directory entries such as `GAMMA~11BIN` at `0x78d840`: an embedded resource file system |
  | `0xa40000`–`0xbc0000` | mixed, high entropy |
  | `0xbc0000`–end | symbol and resource **name tables** (function and variable names) |

- The name tables contain colour pipeline symbols, for example `cnwBasicToneSaturationPointMin`,
  `cnariRGBtoYCcCm4096`, `cnariYCcCmtoRGB256`, `arcnwCrossProcessToneUnsaturated`,
  `MakeToneForContrastControl`, `ImageTuningRelay_GetDefaultSaturationId`,
  `ImageMetaDataSpec_GetColorMatrix`, `AppImageProcessingStillModeToGammaTableIndex`,
  `g_gammaDefaultLut`, `CCmFilter::*`, and the Custom Image list `cntCustomImageUnit*`
  (Natural, Vivid, Portrait, Landscape, Honoka, PopTune, Reversal, BleachBypass, CrossProcess,
  Monotone and scene modes).

### ELF images and symbols (verified by `tools/q7/elfs.py`, `symbols.py`)

- The file holds 13 ELF32 little-endian MIPS images. The ones that matter:

  | File offset | Role | Load address | Stored / in memory |
  |---|---|---|---|
  | `0x200` | burner (`Zburn`), has `.symtab` | `0x80010000` | plain |
  | `0x1026c0` | kernel, 4 segments | `0x80000780` | `0x12d0b8` plain |
  | `0x2402c0` | application part A | `0x8012da80` | `0x20bef0` → `0x3f2300` **packed** |
  | `0x44c204` | application part B | `0x8051fe00` | `0x182408` → `0x2d2e00` **packed** |
  | `0x5ce660` | application part C (+ data at `0x80b62c00`) | `0x807f2c80` | `0x1800cc` → `0x36ff80`, data `0x2d82c` → `0x89780` **packed** |
  | `0xf4aac0` | relocatable with `__ksymtab` (79,537 entries, names cut to 25 characters) | – | plain |

- A complete sorted symbol table precedes it: 122,154 records in three files of the embedded
  FAT16 volume (`MAINSO~3.ADR` u32 addresses at `0xafa6c0`, `MAINSO~5.OFT` u32 name offsets at
  `0xb71ec0`, `MAINSO~7.STR` names at `0xbe96c0`; the spans are those recorded by the Q7
  research repository). `tools/q7/symbols.py` reads it and reports the segment of each address.
  Distribution: kernel 7,597, part A 21,169, part B 15,430, part C 58,603 (+15,619 data),
  other RAM 3,731.
- Colour symbols are in the **packed** parts, for example `cnarwBasicTone512Middle` `0x804b3a70`,
  `arbGammaTable` `0x803944d4`, `g_gammaDefaultLut` `0x80bc8df0`. They cannot be read until the
  packed segments are unpacked.

### Packed segments (solved: `tools/q7/unpack.py`)

- The kernel unpacks them with `InflateElfStream` (`0x800e9cc4`) → `InflatingStreamSetupInputJob`
  (`0x800fae80`) → an inflate processor of the COACH chip that is given lookup tables
  (`IP_LoadVlcTable`). There is no software decoder in the firmware; the format below was
  worked out from the header parser and from the tables themselves.
- A packed segment is a chain of **blocks**. Block header, 16 bytes: `u32 kind (2)`,
  `u32 output bytes`, `u32 data bytes`, `u16 table 1 bytes`, `u16 table 2 bytes`; then table 1
  (literal/length code), table 2 (distance code), then the data (padded to 128 bytes).
  The chains end exactly at each segment's file size and their output sizes add up to the
  memory sizes (`tools/q7/blocks.py`): 178, 126, 125 and 19 blocks.
- The data is LZ77 with **deflate's alphabets** (literals, end of block, lengths 3–258 with 0–5
  extra bits, distance codes with 0–13 extra bits) but with a prefix code given as a hardware
  lookup table instead of deflate's code lengths. Bits are read most significant bit first;
  extra bits likewise.
- Table entries are `u32` (`tools/q7/codes.py`):
  - bits 0–1 = 3: **leaf**. Value in bits 2–11 (0–255 literal, `0x100` end, `0x200 + base`
    length; in table 2 the value is `extra_bits << 2 | 2 | low_bit`, or 0–3 for distances 1–4),
    bits 12–14 number of extra bits, bits 15 and up code bits beyond the table's shortest code
    plus extra bits.
  - bits 0–1 = 0: pointer to a **direct table** of `2^B` slots at `index`; shorter codes
    repeat. `index` = bits 2–10, `B` = bits 11–14, `A` = bits 15–18 (shortest code in it).
  - bits 0–1 = 1: pointer to a **run-class table** of `B + A` entries at `index + 1`: the first
    `B` entries are chosen by a leading run of zeros of length 1…B (`01`, `001`, …, the longest
    without the closing `1`), the next `A` by a run of ones (`10`, `110`, …).
  - Entry 0 is the root pointer.
- Checks: the implied codes are complete prefix codes (Kraft sum exactly 1) for both tables; the
  first block starts with `addiu sp,sp,-0x18; sw s0,0x10(sp); sw ra,0x14(sp)` at the address of
  `EyeFiService_InitializeOnBoot2nd`; all four segments unpack to their exact memory sizes;
  1,153 of 1,779 sampled function symbols in the unpacked parts begin with `addiu sp,sp,-N`;
  **the SHA-256 of each of the four unpacked segments equals the value recorded independently in
  the Q7 research repository** (`analysis/segment-decode.json`). An earlier version of
  `codes.py` masked the leaf length field to three bits and got part B wrong; that comparison
  found it.
- `python3 -I tools/q7/unpack.py firmware.bin image.bin` writes the memory image
  `0x80000600`–`0x80bec380` (12,500,352 bytes, SHA-256 `8287b002…35dc` for this firmware).
  The image is firmware content: keep it out of the repository.
- `Q7_IMAGE=image.bin:0x80000600 python3 -I tools/q7/disasm.py firmware.bin NAME` disassembles
  any function by symbol name (needs `pip install capstone`).

### Colour tables (located and exported: `tools/q7/export_tables.py`, `q7-color-tables.json`)

The Q7 firmware has the same family of colour engine as the K-3 Mark III, with named tables.
All are in unpacked part A. Values are in [`q7-color-tables.json`](q7-color-tables.json).

| Symbol | Meaning (by name and by values) | K-3 III counterpart in `engine.py` |
|---|---|---|
| `cnsCameraBasicMatrix` `0x804add38` | sensor matrix, 1.0 = 8192, rows sum to 8192: `11243 -3459 408 / -2736 12937 -2009 / -2 -4343 12537` | `common_matrix` |
| `cnsMakeUpMatrix<Mode>` | per Custom Image matrix, 1.0 = 8192. Modes: Natural, Vivid, Portrait, Landscape, Miyabi, Monotone, Flat, Honoka, Reversal, BleachBypass, PopTune | `mode_matrix` |
| `cnsMakeUpMatrix<Mode>6` | six matrices per mode (108 bytes); purpose not yet known | – |
| `cnarsSatCtlMatrix00`…`08` | saturation −4…+4, 1.0 = 8192 (`04` is identity) | `saturation_matrix_sets` |
| `cnarsFilterEffectMatrix00`…`08` | monochrome filter effect | saturation set `s1` |
| `cnsHueShiftMatrix00`…`08` | hue −4…+4 as YC rotations, **1.0 = 256** (K-3 III stores 8192) | `hue_matrix_sets` |
| `arcnwYCbCrConversionMatrixDefault` | `77 150 29 / -43 -85 128 / 128 -107 -21`, 1.0 = 256 | `hue_right_matrix` |
| `cnarwBasicTone{128,256,512,1024,2048}{Low,Middle,High}` | 15 tone curves of 256 × u16: three contrast families × **five** columns (K-3 III has six) | `gamma.families` |
| `cnarwReversalTone{128,181,256,362,512,724,1024}` | seven Reversal Film curves (K-3 III has nine) | `gamma.reversal_curves` |
| `arcnlDNGColorMatrix1`, `2` | nine (numerator, 65536) pairs each | `dng_color_matrix_tables` |

### Colour arithmetic (read from the code; port verified by emulation: `tools/q7/q7port.py`, `check_port.py`)

`tools/q7/emu.py` runs routines of the unpacked image in a CPU emulator (unicorn, MIPS32 LE; kseg0
addresses are mapped to physical memory). `tools/q7/check_port.py` runs the two firmware routines
below for many settings and compares every output value with the Python port `tools/q7/q7port.py`:

    MakeColorMatrix: 578/578 settings identical     (11 modes x saturation x hue x colour space x toning)
    CalcGammaCorrectionTable: 308/308 settings identical   (key x contrast x exposure gain x ratio x step)

**`ColorMatchingService_MakeColorMatrix` `0x8041c180`** (arguments: settings, white-balance data or 0,
descriptor A, descriptor B, six-matrix output). Settings fields used: byte `+0x34` mode id,
`+0x35` saturation 0..8, `+0x39` hue 0..8, `+0x3a` filter effect, `+0x3b` monochrome toning,
`+0x3c` toning colour, word `+0x178` gain, `+0x1fc` colour space, `+0x200` development sensitivity
(0..4 -> 128, 181, 256, 362, 512), byte `+0x1a0` a flag that disables the AdobeRGB variants.

- Mode ids (jump table of `GetMakeUpMatrix`): 0 Natural, 1 Vivid, 2 Portrait, 3 Landscape, 4 Miyabi,
  5 Honoka, 6 Reversal, 7 BleachBypass, 8 PopTune, 9 Vivid again, 10 Monotone.
- `MatrixMultiplication(out, A, B)` is `A x B`, 1.0 = 8192, `(sum + 0x1000) >> 13` (logical), low 16 bits.
- Colour matrix: for each of the six make-up matrices, `Sat[sat] x MakeUp6[i] x CameraBasic`
  (mode 10 uses `FilterEffect[filter]` in place of `Sat`), each value divided by 32 towards zero, then
  the diagonal is replaced so every row sums to 256. **Result is 1.0 = 256, like the K-3 III CC0.**
  In firmware 1.01 all six matrices of every mode are equal to the single `cnsMakeUpMatrix<Mode>`,
  so the six outputs are identical.
- Descriptor A (`+0x18`, the CM register block in the Q7 research repository's routing) is **not** the
  colour matrix: it is `256 x identity x gain / 8192`, multiplied by the white-balance gains when
  white-balance data is given, clamped to +-0x7ff. The single matrix the routine also computes on its
  stack (`Sat x MakeUp x CameraBasic x gain`) is not written to any output.
- Descriptor B (`+0x18`, FC1): `HueShift[hue] x YCbCr`, 1.0 = 256, `(sum + 0x80) >> 8`; for AdobeRGB it
  is then multiplied by `arcnsSRGBAdobeRGB` (`5857 2334 0 / 0 8192 0 / 0 335 7856`); the result is
  shifted left by 3 (1.0 = 2048). Modes 5 and 7 always use hue index 4 (no hue control).
- Chroma offsets (descriptor B `+0x2a`, `+0x2c`, stored with `+0x800`): mode 10 takes
  `cnarsCbOffset/cnarsCrOffset[monochrome toning]`; modes 5 and 7 take
  `cnarsCbAddition/cnarsCrAddition[toning colour]`; other modes 0. AdobeRGB has its own tables.

**`GammaCorrectionService_CalcGammaCorrectionTable` `0x8041d058`** (settings, unused, output table of
4096 x u16). Same algorithm as the K-3 III `_regular_curve` with these differences:

- no highlight/shadow adjustment (the three offsets are constant 0);
- five columns: 128, 256, 512, 1024, 2048; `v` is clamped to 128..2048;
- `v = (key_table[key] * ratio / 256 * exposure) >> 13` with key table
  `512 431 362 304 256 215 181 152 128` (the same as the K-3 III), `ratio = 0x400000 / word(+0x174)`
  or 256 when that word is 0, `exposure = word(+0x164)` (0x2000 = 1.0);
- family order High, Middle, Low; contrast weight `2 x contrast x 512 / 12` exactly as the K-3 III;
- only tone table entries 0..128 are used. They are scaled by `4095 / 16130`
  (`cnwBasicToneSaturationPointOutput / cnwBasicToneSaturationPointMin`), limited to 4095 and
  linearly interpolated into table entries 0..2047 (16 per step); entries 2048..4095 are a straight
  line from entry 2048 to 4095.

Not yet read: `GammaCorrectionService_CalcGammaCorrectionTableReversal` `0x8041cd28`, the Custom
Image records `cntCustomImageUnit<Mode>`, `ImageTuningRelay_GetDefault*Id`, where the six-matrix
output goes after `ImageQualityService_SetupColorMatrix`, and how the gamma table input range
(0..4095) relates to the sensor range.

## Next steps

1. Disassemble `ColorMatchingService_MakeColorMatrix` and the tone routine; write down the
   arithmetic and compare it with `engine.py` (`cc0`, `yc`, `_regular_curve`, `_reversal_curve`).
2. Read the Custom Image records (`cntCustomImageUnit*`) and the default-id functions
   `ImageTuningRelay_GetDefault*Id` for factory settings and which controls each mode has.
3. Extract the FAT resource image and list its files (`GAMMA*.BIN` and others); these are plain.
4. Write `q7` engine tables in the format `Engine` needs (or a `Q7Engine` where the arithmetic
   differs) and a `pentax-q7` camera pack with its manifest.
5. App work: second entry in `profiles._PACKS`, camera picker in the GUI, Q7 DNG input in
   `raw.py` (sensor geometry, levels, maker note), `UniqueCameraModel` `PENTAX Q7`, tests, docs.
6. Validation that is possible without a camera: internal consistency only. Lightroom and
   camera JPEG comparisons need Q7 RAW files from the user.

## Open questions for the user

- A Q7 DNG (and, ideally, the camera JPEG of the same shot) is needed to implement and check
  RAW preview and to confirm `UniqueCameraModel`, levels and the DNG colour matrices.
