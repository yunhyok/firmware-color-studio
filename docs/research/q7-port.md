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

### Container and platform (verified by `tools/q7/look.py`, `arch.py`, `strs.py`)

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

## Next steps

1. Find the symbol table that pairs the names at `0xbc0000`+ with addresses, and the load
   address of each code/data section.
2. Identify the `0x240000`–`0x780000` region (compressed main program?) and unpack it.
3. Extract the FAT resource image and list its files (`GAMMA*.BIN` and others).
4. Locate, by symbol, the Custom Image parameter tables: colour matrices, saturation/hue/key/
   contrast tables, gamma and tone tables, YC conversion, chroma suppression.
5. Reconstruct the calculation from those parameters to the ISP registers and write
   `engine`-compatible tables for a `pentax-q7` camera pack.
6. App work: second entry in `profiles._PACKS`, camera picker in the GUI, Q7 DNG input in
   `raw.py` (sensor geometry, levels, maker note), `UniqueCameraModel` `PENTAX Q7`, tests, docs.
7. Validation that is possible without a camera: internal consistency only. Lightroom and
   camera JPEG comparisons need Q7 RAW files from the user.

## Open questions for the user

- A Q7 DNG (and, ideally, the camera JPEG of the same shot) is needed to implement and check
  RAW preview and to confirm `UniqueCameraModel`, levels and the DNG colour matrices.
