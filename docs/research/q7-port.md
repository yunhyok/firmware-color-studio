# PENTAX Q7 camera pack: research log and hand-over

Goal: add **PENTAX Q7** as a second, selectable camera in Firmware Color Studio, with DCP recipes
derived from its firmware in the same way as the K-3 Mark III pack. This file is the working
record. It is updated at every milestone so that the work can be resumed from here.

**Status: in progress (research phase). The firmware is fully unpacked and symbolised; the colour tables are not located yet. Nothing in the app has changed yet.**

## How to resume

1. Read "Findings" and "Next steps" below. Each finding states how it was obtained.
2. The firmware is not in the repository and must not be committed (`*.bin` is ignored).
   Input used: `fwdc603p.bin`, 18,743,520 bytes,
   SHA-256 `8a928b574623c28624127501526d8496a98a42eac3d843def6d3b5ceb074ff3b`.
3. The scripts in `tools/q7/` take the firmware path as their first argument and only read it:
   `python3 -I tools/q7/<script>.py /path/to/fwdc603p.bin`.
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

- A complete sorted symbol table precedes it: 122,368 entries, u32 addresses at `0xafa368`,
  u32 name offsets at `0xb71b68`, names from `0xbe96c0`. `tools/q7/symbols.py` reads it and
  reports the segment of each address. Distribution: kernel 7,597, part A 21,169, part B 15,430,
  part C 58,603 (+15,619 data), other RAM 3,945.
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
  extra bits likewise. A block's last match may run past the block's output size and is cut.
- Table entries are `u32` (`tools/q7/codes.py`):
  - bits 0–1 = 3: **leaf**. Value in bits 2–11 (0–255 literal, `0x100` end, `0x200 + base`
    length; in table 2 the value is `extra_bits << 2 | 2 | low_bit`, or 0–3 for distances 1–4),
    bits 12–14 number of extra bits, bits 15–17 code bits beyond the table's shortest code
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
  1,153 of 1,779 sampled function symbols in the unpacked parts begin with `addiu sp,sp,-N`.
- `python3 -I tools/q7/unpack.py firmware.bin image.bin` writes the memory image
  `0x80000600`–`0x80bec380` (12,500,352 bytes, SHA-256 `eb0e5607…f45e` for this firmware).
  The image is firmware content: keep it out of the repository.
- `Q7_IMAGE=image.bin:0x80000600 python3 -I tools/q7/dis.py firmware.bin NAME` disassembles
  any function by symbol name (needs `pip install capstone`).

## Next steps

1. With the unpacked image and `symbols.py`, read the Custom Image parameter tables: colour
   matrices, saturation/hue/key/contrast tables, gamma and tone tables, YC conversion, chroma
   suppression (`cnarwBasicTone*`, `arbGammaTable`, `ImageTuningRelay_*`, `CCmFilter::*`,
   `MakeToneForContrastControl`, `cntCustomImageUnit*`).
2. Extract the FAT resource image and list its files (`GAMMA*.BIN` and others); these are plain.
3. Reconstruct the calculation from those parameters to the ISP registers and write
   `engine`-compatible tables for a `pentax-q7` camera pack.
4. App work: second entry in `profiles._PACKS`, camera picker in the GUI, Q7 DNG input in
   `raw.py` (sensor geometry, levels, maker note), `UniqueCameraModel` `PENTAX Q7`, tests, docs.
5. Validation that is possible without a camera: internal consistency only. Lightroom and
   camera JPEG comparisons need Q7 RAW files from the user.

## Open questions for the user

- A Q7 DNG (and, ideally, the camera JPEG of the same shot) is needed to implement and check
  RAW preview and to confirm `UniqueCameraModel`, levels and the DNG colour matrices.
