# PENTAX Q7 camera pack: research log and hand-over

Goal: add **PENTAX Q7** as a second, selectable camera in Firmware Color Studio, with DCP recipes
derived from its firmware in the same way as the K-3 Mark III pack. This file is the working
record. It is updated at every milestone so that the work can be resumed from here.

**Status: in progress (research phase). Nothing in the app has changed yet.**

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

### Packed segments (not solved)

- The kernel unpacks them with `InflateElfStream` (`0x800e9cc4`) → `InflatingStreamCreate/Decode`
  (`0x800f9ba8`) → an "inflate processor" object called through function tables
  (`InflateProcessorCreate` `0x800fa13c`, `gsInflateProcessor`, `sInflateCguUnits`: probably a
  hardware block of the COACH chip).
- The stream is **not** RFC 1951 deflate in any simple form: raw deflate, zlib and gzip were tried
  at every start offset 0–4095 of segment A, also with 16/32-bit byte swaps and bit reversal.
- Segment data starts with what looks like a header and a table, for part A:
  `00000002 000045ac 00002700 0084058c 00069801 0001a84c 00008841 0000080f 0002b48c 0002b38c …`.
  Parts B and C start with `2, 0x4660, 0x2800` and `2, 0xab04, 0x2d00`.
- `tools/q7/dis.py firmware.bin NAME` disassembles kernel functions by symbol name (needs
  `pip install capstone`).

## Next steps

1. **Unpack the three packed parts.** Read the inflate processor code in the kernel (function
   tables behind `InflatingStreamDecode`, `InflateProcessorCreate`) and look for a software
   decoder; work out the header/table at the start of each packed segment.
2. Extract the FAT resource image and list its files (`GAMMA*.BIN` and others); these are plain.
3. With the unpacked image and `symbols.py`, read the Custom Image parameter tables: colour
   matrices, saturation/hue/key/contrast tables, gamma and tone tables, YC conversion, chroma
   suppression (`cnarwBasicTone*`, `arbGammaTable`, `ImageTuningRelay_*`, `CCmFilter::*`,
   `MakeToneForContrastControl`, `cntCustomImageUnit*`).
4. Reconstruct the calculation from those parameters to the ISP registers and write
   `engine`-compatible tables for a `pentax-q7` camera pack.
5. App work: second entry in `profiles._PACKS`, camera picker in the GUI, Q7 DNG input in
   `raw.py` (sensor geometry, levels, maker note), `UniqueCameraModel` `PENTAX Q7`, tests, docs.
6. Validation that is possible without a camera: internal consistency only. Lightroom and
   camera JPEG comparisons need Q7 RAW files from the user.

## Open questions for the user

- A Q7 DNG (and, ideally, the camera JPEG of the same shot) is needed to implement and check
  RAW preview and to confirm `UniqueCameraModel`, levels and the DNG colour matrices.
