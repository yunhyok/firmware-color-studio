# Data and processing

The firmware modes follow the K-3 III formulas and numeric tables at research commit `aa885bcdaee874d9b9bb18663dd62ed10263eda2`. A separate Studio tool fits a JPEG look using ColorChecker Classic measurements and writes a standalone DCP through the shared serializer. Both workflows run locally. [Camera pack manifest](../src/firmware_color_studio/data/k3iii/manifest.json) · [JPEG chart profiles](chart-profiles.md)

`engine.py` implements the original integer setting calculations. `color_model.py` applies matrix, gamma, YC and chroma operations. `gold.py` adds verified physical R/G/B integer tables. `profiles.py` validates versioned recipes, selects a camera pack, builds DCPs and renders them. `enhanced.py` adds a neutral DCP and an Adobe RGB-table XMP where DCP HSV tables cannot represent the effect. `raw.py` reads the original sensor mosaic through LibRaw and prepares white-balanced half-resolution camera RGB. `display.py` converts the result from sRGB to the current window's monitor ICC. The Qt UI runs decoding, rendering and exports off the GUI thread.

## Camera packs

The private `_PACKS` registry in `profiles.py` maps stable camera IDs to independent manifest/data paths, labels, engines and enhanced-mode implementations. Recipes pin `camera_id`, `pack_version` and `schema_version`; unknown versions and parameters fail explicitly. The first pack is `pentax-k3iii`, version `2.20-1`.

Adding a camera requires its own sourced numerical model, manifest/default recipes, supported RAW identity and metadata/crop validation in `raw.py`, and comparison tests. Do not reuse K-3 III color matrices, black levels or firmware layouts merely because a camera is also PENTAX. The current GUI has one available pack; a camera picker becomes useful when a second validated pack exists. The packaged application never needs the manufacturer's firmware binary.

## Defaults and custom profiles

The sixteen original default DCP files are immutable templates with checked hashes. Default export replaces only the TIFF ProfileName entry and appends its UTF-8 English/Korean text. Numerical tags remain byte-for-byte unchanged. Custom settings recalculate the firmware engine and sample a DCP LookTable and tone curve; supplied calibration changes the ColorMatrix pair used for white balance, not the firmware's fixed color processing.

The six controls are integer firmware inputs, including Key brightness, rather than a second Lightroom exposure slider. Controls ignored by a mode are disabled. Gold accepts highlight and shadow in the underlying firmware routine, while the camera's factory UI metadata marks them unavailable; the app exposes these verified extended calculations without claiming they appear in the camera menu. Internal state fields without an established user-facing meaning are not presented as creative controls.

DCP saturation-zero entries cannot introduce tint to neutral pixels, and a shared DCP tone curve cannot directly carry independent Gold channel curves. These recipes use the documented Adobe enhanced-profile mechanism. See [enhanced.md](enhanced.md) for LUT storage, processing order and approximation.

## Data safety and reproducibility

RAW files are opened read-only. GUI saves require the correct output suffix, reject input aliases, write to a temporary file and replace the destination only after the save dialog. Only one export runs at a time. CLI exports use exclusive creation. Stale background completions cannot replace the latest RAW or preview. The displayed RAW stays in use until a newly opened file has loaded, so a rejected file leaves the current preview working. A recipe and its hash accompany enhanced exports so the settings are recoverable.

A release is published by pushing the tag `v<version>`, or by running the workflow manually on `main` with **release** checked, which creates that tag at the built commit. Both require `docs/releases/v<version>.md`. Installer builds run the offline tests first. CI uses Windows and independently checks the frozen application against every registered default mode. Firmware-emulator verification is optional development work and remains outside the installer. [Gold reproduction instructions](gold.md#verification-and-reproduction)
