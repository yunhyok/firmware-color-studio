# PENTAX Q7 camera pack: research log and hand-over

Goal: add **PENTAX Q7** as a second, selectable camera in Firmware Color Studio, with DCP recipes
derived from its firmware in the same way as the K-3 Mark III pack. This file is the working
record. It is updated at every milestone so that the work can be resumed from here.

**Status: the `pentax-q7` camera pack is in the app (camera menu, CLI `--camera`, Q7 DNG input) and builds DCP and DCP + XMP profiles for ten Custom Images. Its integer calculations, including the basic gamma and the 9 x 9 x 9 table, reproduce the emulated firmware exactly, and the Landscape profile matches the camera JPEG of one Q7 photograph to a mean Delta E76 of 1.5. Not done: Lightroom, other sensitivities and Custom Images on photographs, and the items under "Next steps".** User documentation: [../q7.md](../q7.md).

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
| `cnsMakeUpMatrix<Mode>6` | six matrices per mode (108 bytes), one per hue sector of the three-dimensional table; all six equal the single matrix in firmware 1.01 | – |
| `cnarsSatCtlMatrix00`…`08` | saturation −4…+4, 1.0 = 8192 (`04` is identity) | `saturation_matrix_sets` |
| `cnarsFilterEffectMatrix00`…`08` | monochrome filter effect | saturation set `s1` |
| `cnsHueShiftMatrix00`…`08` | hue −4…+4 as YC rotations, **1.0 = 256** (K-3 III stores 8192) | `hue_matrix_sets` |
| `arcnwYCbCrConversionMatrixDefault` | `77 150 29 / -43 -85 128 / 128 -107 -21`, 1.0 = 256 | `hue_right_matrix` |
| `cnarwBasicTone{128,256,512,1024,2048}{Low,Middle,High}` | 15 tone curves of 256 × u16: three contrast families × **five** columns (K-3 III has six) | `gamma.families` |
| `cnarwReversalTone{128,181,256,362,512,724,1024}` | seven Reversal Film curves (K-3 III has nine) | `gamma.reversal_curves` |
| `arcnlDNGColorMatrix1`, `2` | nine (numerator, 65536) pairs each | `dng_color_matrix_tables` |
| `cnwHighlightShadowCompositionRate2048` `0x804b4a78` | 97 rates of 0..2048 that join two tone curves around the reference grey; used by the basic gamma | `gamma.transition_weights` (the same values) |

### Colour arithmetic (read from the code; port verified by emulation: `check_port.py`)

`tools/q7/emu.py` runs routines of the unpacked image in a CPU emulator (unicorn, MIPS32 LE; kseg0
addresses are mapped to physical memory). `tools/q7/check_port.py` runs the two firmware routines
below for many settings and compares every output value with the Python port (the first port, a
stand-alone script, has since become `q7_engine.py`; its counts were):

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

**`GammaCorrectionService_CalcGammaCorrectionTableReversal` `0x8041cd28`** has the same form with
seven curves (`cnarwReversalTone128`…`1024`, bounds `128 181 256 362 512 724 1024`), `v` clamped to
128..1024, the key fixed at 0 and no contrast. Port verified with the regular table (906 tables).

`check_port.py` now compares the engine the app uses (`src/firmware_color_studio/q7_engine.py`):

    MakeColorMatrix (six colour matrices, CM, FC1, chroma offsets): 276/276 settings identical
    CalcGammaCorrectionTable and ...Reversal (4096 entries each): 1636/1636 settings identical
    CalcBasicGammaCorrectionTable (4096 entries) and MakeColorReproductionLutParam (729 points): 794/794 settings identical

**The nominal ratio is `0x2000`, so `v = 512`.** `ImageQualityService_SetupGammaCorrectionAndColorMatchingService`
copies the settings for a second set of tables (when byte `+0x1a0` is 1) and writes `0x2000` to both `+0x174` and
`+0x178` of the copy (`0x80428ddc`...`0x80428de4`). With `+0x174 = 0x2000` the ratio is `0x400000 / 0x2000 = 512`,
the constant the K-3 Mark III has in the same place of `_regular_curve`. The earlier default of this port was the
routine's fallback for a zero word (256), which puts the reference grey at input 256 of 4096; with 512 it is at
input 512, one eighth of the range. The photograph below confirms 512.

**`GammaCorrectionService_CalcBasicGammaCorrectionTable` `0x8041d7e8`** (settings, output table of 4096 x u16).
It reads only the run-time words (`+0x164`, `+0x174`, the coarse flag `+0x1a0`), not the Custom Image or its
settings: emulated tables for all modes, keys, contrasts and saturations are equal. It is the K-3 Mark III's
highlight and shadow contrast calculation with fixed amounts:

- three tone curves with contrast amounts -7, -4 and -6 (that is contrast -2, highlight -3, shadow -2), each
  mixed from the Low and Middle families and joined to the reference grey as in the regular table;
- below the reference grey the middle curve is mixed with the -6 curve, above it with the -7 curve, by
  `cnwHighlightShadowCompositionRate2048[32 x ratio - 32]` (97 entries of 0..2048; `ratio` is `x / v` above and
  `v / x` below; beyond a factor of four the outer curve is used alone). These rates equal the K-3 Mark III's
  transition weights value for value;
- all 256 tone points are used, 16 table entries per point, scaled by `4095 / 16130` and limited to 4095 (the
  regular table uses points 0..128 and a straight line above).

Ported for the nominal gains (`v = 512`): `Q7Engine.basic_gamma`. Values: entry 512 is 1917 (the reference grey),
entries 256, 1024, 2048 are 1299, 2530, 3181.

### Where the results go: a three-dimensional table (ported and emulated)

`ImageQualityService_SetupGammaCorrectionAndColorMatchingService` `0x804289b8` allocates four gamma
tables and three descriptors and calls:

- `GammaCorrectionService_SetupGammaCorrectionData` `0x8041e27c`: table A = the routine above (Reversal
  for mode id 6); tables B and C are marked unused (`0xffff`) unless Cross Processing fills them; table
  D = `CalcBasicGammaCorrectionTable`, which is encoded for the hardware gamma block (descriptor id 10).
- `ColorMatchingService_MakeColorReproductionLutParam` `0x8041c7dc` (via `SetupColorReproductionLuts`,
  descriptor id 0x13, 0x19c0 bytes): a 9 x 9 x 9 table of RGB triples. The nine node levels per axis
  are where table D first reaches `0 512 1024 ... 3584 4095`. For each node: choose one of the six
  matrices by the order of R, G, B (hue sector); `matrix x RGB >> 8`; convert to Y, Cb, Cr
  (`306 601 117 / -173 -339 512 / 512 -429 -83`, `>> 10`); if the matrix output's green is <= 256,
  scale Cb and Cr by `arwCChromaSuppressionRatioLut[min(2 x (256 - green), 2047)] / 8192` (1.0 down to
  0.875 at black); convert back (`1436`, `-352 -731`, `1815`, `>> 10`); clamp to 0..4095; look each
  channel up in gamma table A (B, C for Cross Processing).

So the camera's colour rendering is this table, addressed by the output of the basic gamma block and
interpolated by the hardware. At the nodes it equals `gamma(chroma suppression(matrix x RGB))`. The gamma
routines do not read the colour space setting.

Details found when porting (`Q7Engine.reproduction_table`, `table_inputs`):

- Arguments: settings, unused, output, six matrices, gamma tables A, B, C, basic gamma table D. The output
  holds 729 RGB triples of u16 from offset `0x18`, red outermost: `0x18 + 486 R + 54 G + 6 B`.
- The node inputs are found by one pass over table D: each entry gives at most one node, and the ninth is
  set to 4095. With the nominal table D they are `0, 75, 179, 337, 591, 1060, 1845, 2876, 4095`.
- Every division rounds towards zero. The chroma ratio index is `2 x (256 - G)` limited to 0..2047 with G
  the matrix output's green, so a strongly negative green (a saturated red or blue) is desaturated most.
- Selection among the six matrices: index `4 (G < B) + 2 (R < B) + (R < G)` into the pointers
  `[0, 1, -, 2, 5, -, 4, 3]`. All six are equal in firmware 1.01.

`color_model.CameraColour._table_codes` looks a colour up as the image processor would: basic gamma per
channel, position between the levels `0, 512, ... 3584, 4095`, tetrahedral interpolation (the cube cut along
its grey diagonal). The interpolation rule is not in the firmware; see the photograph.

### A Q7 photograph (2026-11-22): what the camera does with the tables

`20261122-IMGP1138.DNG`: ColorChecker Classic (Passport), firmware 1.01, ISO 100, 1/100 s, f/1.9, Landscape at
factory settings (saturation 0, contrast +1, sharpness +1), sRGB, aspect ratio 3:2, daylight from a window. The
DNG holds the camera's JPEG of the shot (SubIFD1, 1920 x 1280). Patches: median of 81 samples per patch, the
raw ones from the white-balanced mosaic at half resolution. Numbers: [../chart-session-validation.json](../chart-session-validation.json),
script `tools/chart_session.py`.

- **File structure.** 4064 x 3000 samples of 12 bit, uncompressed; `ActiveArea 0 0 3000 4000`; `BlackLevel 0`,
  `WhiteLevel 4062` (the maker note has `BlackPoint 32`: the black level is already subtracted);
  `DefaultCropOrigin 0 168`, `DefaultCropSize 4000 2664` for the 3:2 setting; `BaselineExposure -32768/65535`.
- **DNG tags against the firmware.** `ColorMatrix1` and `2` equal `arcnlDNGColorMatrix1` and `2`. Maker note
  tag `0x021c` (ExifTool `ColorMatrixA2`) is `arcnsSRGBAdobeRGB` (`5857 2334 0 / 0 8192 0 / 0 335 7856`). Tag
  `0x021d` (`ColorMatrixB2`, `13952 -4416 -1344 / -1472 13792 -4128 / 128 -2816 10880`, rows sum to 8192) is
  none of the exported matrices and not the colour matrix of the shot; what it is was not found. The maker
  note model number is 77690, the number in the firmware trailer. Settings are in tags `0x004f` (Custom Image
  3), `0x001f` saturation 1, `0x0020` contrast 4, `0x0021` sharpness 4, `0x0067` hue 1, `0x006c` key `0 0`:
  with ExifTool's value table (1 = 0, 4 = +1) these are the factory Landscape record.
- **Exposure.** The six greys are at `0.831 0.590 0.383 0.206 0.096 0.035` of the white level after white
  balance. With `v = 512` the tables meet the JPEG's greys at +0.03 EV (matrix and gamma alone) or +0.06 EV
  (with the table) of that level; with `v = 256` only at -0.94 EV, and with a grey error of 1.14 L* in place
  of 0.36. So the gamma input is the sensor level, `v = 512`, and the DNG's `BaselineExposure` of -0.5 is
  cancelled by `BaselineExposureOffset` +0.5 in the pack, as in the K-3 Mark III pack.
- **Interpolation.** Mean Delta E76 over the 24 patches at the sensor level: 3.22 with matrix, clip and gamma
  applied directly; 3.25 with the table interpolated trilinearly (greys off by 3.1 L*); **1.51 with the table
  interpolated tetrahedrally** (greys 0.9 L*; 1.31 at +0.06 EV). The direct calculation cuts the weakest channel
  of saturated colours to zero where the camera does not (yellow green: blue 40 against the JPEG's 73; magenta:
  green 70 against 93); the table gives 71 and 90. On the grey axis a trilinear rule would mix in the
  neighbouring coloured nodes, which the JPEG does not show.
- **The exported profile.** The Landscape DCP rendered with the file's `BaselineExposure`: 1.49 (colours 1.58,
  greys 1.22, largest 7.60 at yellow, where the JPEG has blue 53 and the model 17). DCPs of other Custom Images
  on the same file: Bright 3.90, Portrait 5.24, Vibrant 6.53, Natural 11.57.

### Custom Image records and DNG matrices

`cntCustomImageUnit<Mode>` (28 bytes): byte 0 mode id, 1 saturation, 2 contrast, 3 sharpness, 4 key,
5 hue, 6 monochrome filter effect, 7 monochrome toning, 8 toning colour (settings stored as 0..8, 4 =
0). The bytes are copied to settings `+0x34`…. The values equal the K-3 Mark III factory settings for
the same Custom Images (Bright contrast +1; Radiant key +2, contrast +3; Muted key +4, contrast -3;
Bleach Bypass key -4, contrast +4, toning green). The toning offsets divided by 4 equal the K-3 III's.
There are also records for scene modes (`DramaticArt`, `Gokusai`, `BlueSky`, …) that are not offered.

`arcnlDNGColorMatrix2` equals the D65 matrix LibRaw lists for the Q-S1 (same sensor):
`12995 -5593 -1107 / -1879 10139 2027 / -64 1233 4919` (x 1e-4). The model string in the firmware is
`PENTAX Q7`.

## Next steps

Done on 2026-11-22 with the photograph above: the exposure anchor (+0.5 EV), Q7 DNG input with the shot's
settings and calibration import, the comparison with the camera JPEG, and the model of the table.

1. **Lightroom.** Render the Q7 DNG with the exported profiles in Lightroom Classic and compare with Studio's
   renderer and the camera JPEG, as `docs/validation.md` does for the K-3 III.
2. **Run-time gains.** Find what writes settings `+0x164` and `+0x174` in shooting (sensitivity, highlight and
   shadow correction) and port the rest of `CalcBasicGammaCorrectionTable` for other values. A DNG at a high
   sensitivity or with highlight correction on, with its JPEG, would show whether `BaselineExposure` follows.
3. **More photographs.** Other Custom Images and non-zero settings (hue and key in particular: their maker note
   values come from ExifTool's table and were seen only at zero), AdobeRGB, and a full-size camera JPEG.
4. The yellow patch (Delta E 7.6): the JPEG keeps more blue than the table. Check a full-size JPEG before
   looking for another stage.
5. Where the maker note records the toning colour of Muted; what maker note tag `0x021d` is.
6. Optional: Cross Processing, monochrome filter effect and monochrome toning.
7. Extract the FAT resource image and list its files (`GAMMA*.BIN` and others); not needed so far.
