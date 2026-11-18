# Enhanced-profile boundary fidelity

This report records the v0.1.2 baseline. See the [current enhanced profile measurements](enhanced.md#preview-and-validation) for the comparison with v0.1.3.

The v2 enhanced-profile builder moves the firmware colour matrix (CC0) into the
paired DCP, before the RGB LUT. It also fixes a separate Gold gamma evaluation
bug at input zero. These changes follow the verified firmware tables and Adobe's
processing order; no photographs were used to choose matrices, curves, or LUT
parameters.

The exported LUT remains **32×32×32, 16-bit, ProPhoto primaries with the sRGB
transfer function and tetrahedral interpolation**. The DCP and XMP must be used
together. **Selecting the v2 base DCP by itself does not produce correct colours**:
its intermediate coordinates acquire their colour-space meaning in the paired
XMP. Existing standalone DCP exports retain their original construction.

## Two distinct corrections

`CameraColour.gamma()` previously multiplied its result by `sign(input)`, which
forced input zero to output zero. Gold's original physical B table starts at
96/1023 in sRGB mode and 120/1023 in Adobe RGB mode. The corrected evaluator
retains the first table entry at zero and mirrors only negative inputs used by
the extension path. Ordinary curves whose first entry is zero are unaffected.

The first entries were checked again by executing the original ARM tuning code
at the nominal state in both spaces. Each complete 3×4096 response also matched
the runtime model. The firmware hash, output digests, and limits are recorded in
`verify_zero.json`; [Gold provenance](gold.md) describes the earlier complete
table and physical register-routing verification. This is emulator evidence,
not execution of camera hardware or ISP pixels.

The previous LUT encoded both CC0 and the later nonlinear stages after a common
sensor-to-ProPhoto DCP. Adobe clipped that intermediate RGB before the LUT.
Some valid input triplets therefore lost information before the firmware's own
CC0 clip, and the LUT had to interpolate across oblique clipping boundaries.

Let `M` be the verified CC0 matrix and `P` the ProPhoto-to-XYZ matrix. The new
base uses `ForwardMatrix = P M`. Before serialization, Adobe's conversion back
to ProPhoto therefore gives `P⁻¹ P M x = M x`. Its clipping cube now coincides
with the firmware's pre-gamma clipping cube. The LUT evaluates the remaining
gamma → YC → chroma suppression → toning → JPEG RGB stages and converts their
output to real ProPhoto RGB. It contains no inverse sensor-gamut extension.
See [enhanced.py](../src/firmware_color_studio/enhanced.py) and the stage order in
[color_model.py](../src/firmware_color_studio/color_model.py).

Adobe reads ForwardMatrix coefficients at four decimal places and normalizes
their XYZ row sums to D50. It also normalizes its RGB colour-space matrices.
The builder and preview reproduce these operations. If `A` is the effective
serialized camera-to-intermediate matrix, the LUT applies `M A⁻¹` to compensate
the rounding difference before the firmware stages. Clipping has already
discarded values outside `A`'s cube, so this compensation is not lossless.

All 306 supported mode × saturation (−4…4) × colour-space CC0 matrices have
row sums exactly one. Across those matrices, SDK rounding and normalization
move an input-cube coordinate by at most **0.000466857** before compensation.
The bound is obtained at cube corners, where a linear difference reaches its
extrema. Both the serialized matrix and its normalization are covered by tests.

Base names and filenames now contain a v2 marker and a digest of CC0 plus the
calibration matrices. Changing colour space or saturation cannot silently reuse
an old base. Compatible toning variants can still share a base. The XMP UUID
includes the recipe, DCP hash, LUT fingerprint, and format version; the unique
UUID-based XMP filenames introduced in v0.1.1 remain in place.

## Re-evaluating the previously reported 59/255 case

For default Gold/Adobe RGB and white-balanced sensor input
`[0.7850411286188153, 0.7747761263451224, 0.20276238894425247]`, the old direct
model returned `[0.9353315653, 0.9510393681, 0]`. The published v1 LUT returned
`[0.9350822111, 0.9495093095, 0.2319131177]`, giving the reported blue difference
of **59.138/255**. That reference was wrong because it erased Gold's B entry at
zero.

The corrected direct result, using Adobe-normalized RGB primaries for the
output-space conversion, is `[0.9347244464, 0.9495048701, 0.2663608129]`.
Against this single corrected reference:

| Construction | Blue output | Maximum RGB error, units /255 |
| --- | ---: | ---: |
| Published v1, including the zero-entry bug | 0.231913118 | 8.784 |
| v1 with only the zero-entry bug corrected | 0.273650150 | 1.859 |
| v2 matrix staging and SDK normalization | 0.262156298 | 1.072 |

Thus **59→1 is not a valid measure of the LUT-staging improvement**. The model
correction changes the reference. The comparison above isolates that correction.
For the separate default Gold/sRGB input
`[0.20953687713522073, 0.8608416551900554, 0.9950363874156818]`, the zero-entry
correction does not change the direct result; v2's largest error is 1.321/255.

## Deterministic synthetic validation

`validate.py` records three constructions against the same corrected reference:
published v1, v1 with only the gamma-zero correction, and v2. The reference
evaluates firmware-derived stages directly and uses the SDK-normalized primaries
for the final conversion to sRGB. It does not sample the exported LUT.

The nominal-exposure run contains **198 recipes and 18,666,801 RGB triplets**:
all 17 mode defaults in both spaces; all eight nonzero tints in Muted,
Bleach Bypass, and HARUBENI in both spaces; each enabled slider's −4/+4 endpoints
for Gold and those three tinted modes; and four mixed endpoint combinations.
Each recipe uses a full 33³ sensor grid, 50,000 seeded uniform samples, 5,000
seeded dark samples, the two regression inputs, and samples on both sides of
each CC0 clipping plane. No output-gamut filter removes difficult inputs.

All errors below are absolute **encoded sRGB channel differences multiplied by
255**. They are neither perceptual colour differences nor claims about a real
photograph. Each row compares v2 with v1 **after** fixing the zero-entry bug.

| Recipe | Old mean | New mean | New p95 | New p99 | Old max | New max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gold, sRGB | 0.933 | 0.221 | 0.762 | 1.455 | 110.379 | 4.015 |
| Gold, Adobe RGB | 0.585 | 0.240 | 0.852 | 1.719 | 96.588 | 18.923 |
| Muted, tint 1, sRGB | 3.861 | 0.071 | 0.283 | 0.726 | 152.025 | 6.522 |
| Muted, tint 1, Adobe RGB | 3.816 | 0.064 | 0.233 | 0.720 | 191.665 | 10.030 |
| Bleach Bypass, tint 1, sRGB | 2.104 | 0.103 | 0.432 | 0.987 | 73.494 | 2.697 |
| Bleach Bypass, tint 1, Adobe RGB | 2.319 | 0.107 | 0.462 | 1.088 | 106.223 | 8.034 |
| HARUBENI, tint 4, sRGB | 2.393 | 0.076 | 0.359 | 0.631 | 134.302 | 2.482 |
| HARUBENI, tint 4, Adobe RGB | 1.919 | 0.075 | 0.316 | 0.635 | 155.564 | 12.429 |

Every tested recipe has a lower maximum error with v2. Across the 198 recipes,
the largest individual-recipe mean/p95/p99/max is respectively
**0.380/1.232/2.938/29.481**. These are maxima of per-recipe statistics, not
percentiles of a pooled distribution. The former largest maximum was 219.141.

The remaining worst case is Muted/Adobe RGB, tint 1, key −4, input
`[0.27657142871675555, 0.8396712484216707, 0.030468958490673992]`.
Direct sRGB is `[0, 0.9984821891, 0]`; v2 produces
`[0.1156106610, 0.9860256981, 0]`. The red difference is 29.481/255.
At this point the SDK matrix/clip correction alone contributes at most
0.0041/255. The finite LUT changes linear sRGB red from −0.001055 to +0.012619,
which becomes visible at the final sRGB clipping boundary. The LUT remains an
approximation even though the firmware's integer gamma tables are exact.

An additional 32 cases cover total Adobe exposure −2, −1, +0.5, and +1 EV for
Gold and the three tint-capable mode defaults in both spaces. The reference
for these cases deliberately inserts Adobe's exposure operations at their
documented location. Their largest maximum is 15.651/255. These checks validate
pipeline structure; they do not establish firmware exposure-gain behavior.

## Supported format and limits

Adobe's *Enhanced Profiles.pdf*, pages 3 and 9, specifies a 32³ maximum and
states that larger imported cubes are downsampled. Page 18 permits a custom
base DCP for a special-purpose enhanced profile. Pages 3 and 20 place RGB LUTs
late in processing. The builder keeps that documented format; it does not rely
on the local SDK copy's experimental 64³ read/write changes. No alternate
primaries or transfer function is introduced.

Source references in Adobe DNG SDK 1.7.1 (`dng_sdk/source/`):

| Source | Relevant behavior |
| --- | --- |
| `dng_camera_profile.cpp:335–388` | ForwardMatrix row normalization and 1e−4 rounding |
| `dng_color_spec.cpp:177,213,593–595` | Normalize both illuminants; use ForwardMatrix with white balance |
| `dng_color_space.cpp:205–226,993–1000` | Normalize RGB-to-PCS matrices; ProPhoto coefficients |
| `dng_reference.cpp:1389–1440` | Clip camera values and transformed intermediate RGB |
| `dng_render.cpp:1960–2040` | Exposure ramp → LookTable → tone curve → RGB tables |
| `dng_big_table.h:628–690` | 32³ documented limit, primaries/gamma enums, stream version |
| `dng_reference.cpp:3476` (`RefRGBtoRGBTable3D`) | Tetrahedral RGB-table interpolation |

The offline input is already white-balanced sensor RGB, clipped to [0,1].
Normalization and LUT sampling do not validate arbitrary camera calibration,
negative sensor values, overrange/HDR data, demosaicing, noise reduction,
sharpening, or local processing. Gold remains at its previously verified nominal
state: exposure gain 8192, project row 0, no custom-curve/override state.

Negative total Adobe exposure uses a white-preserving tone operation, not a
uniform multiplication of firmware input. User edits also occur between the
base and the late LUT. An exact match to camera JPEGs or to every Adobe edit
setting is therefore not claimed. A 198-recipe finite sample is not an
exhaustive bound over all RGB values and all 9⁶ slider combinations.

## Reproduction and evidence

The research repository publishes the [full numerical evidence](https://github.com/yunhyok/pentax-k3iii-firmware-analysis/blob/main/analysis/gold-lut-fidelity.json), [original ARM zero-entry check](https://github.com/yunhyok/pentax-k3iii-firmware-analysis/blob/main/analysis/gold-gamma-zero.json), and [Korean research report](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/gold-enhanced-profile.html#lut). The JSON includes each recipe, worst input/output triplet, statistics, and source hashes.

Run the public tools from that research checkout, using this app at tag `v0.1.2`:

```powershell
python tools/check_gold_lut_fidelity.py --app-repo PATH_TO_APP --output new-lut-check.json
python tools/verify_gold_gamma_zero.py PATH_TO_DECODED_BIN --app-repo PATH_TO_APP --harness tools --output new-zero-check.json
```

The focused application tests are `python -m pytest tests/test_gold.py tests/test_enhanced.py`.
The firmware check requires the published tuning harness at commit
`aa885bcdaee874d9b9bb18663dd62ed10263eda2` and a user-supplied decoded image;
the loader checks its RTOS SHA-256. Firmware, decompiled code, SDK source, and
photographs are not distributed in that research evidence set. Actual Adobe
import/render evidence is documented separately in [validation.md](validation.md).
