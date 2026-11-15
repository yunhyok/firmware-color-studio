# K-3 III Gold color model

`gold_camera(engine, settings, color_space='srgb', runtime=None)` returns a
`CameraColour` whose three 4096-entry gamma curves reproduce the final integer
R/G/B tables prepared by the original K-3 III firmware 2.20 tuning routine at
the fixed nominal state below. The module requires no firmware or emulator at
runtime. No photographic fitting is used.

The model accepts the six existing settings (`saturation`, `hue`, `key`,
`contrast`, `highlight`, `shadow`) as integers from −4 to +4, and `srgb` or
`adobergb`. Omitted settings are zero. Gold is tuning ID 31, factory record 33,
and MakerNote ImageTone 17. Its factory six settings are zero; the factory
record marks highlight and shadow unavailable, although the original tuning
routine demonstrably accepts and applies both. The app's extended settings
therefore describe firmware calculations, not a claim about menu availability.

## Calculation and sources

1. Reuse the existing integer regular-gamma formula, with key/contrast/highlight
   and negated shadow, to produce the common 256-point curve. Whole Make traces
   enter stage `0x53137564`, base generator `0x53136728` and regular function
   `0x53135da0`.
2. The real getter `0x5313de6c` returns three fixed 256×u16 tables at
   `0x53c1557c`, `0x53c1598c`, and `0x53c15d8c`. Channel preparation
   `0x531368e0` selects Gold when setting `+0x98` is zero and `+0x99` is set.
   For each common-curve value `x`, use `q=x>>6`, `f=x&63`, and
   `C[q] + trunc_toward_zero((C[q+1]−C[q])*f/64)`; values `x>=16320` use
   `C[255]`. The fourth table is `Y=(77R+150G+29B)>>8`.
3. The final stage `0x53137144` calls `0x53136f4c`. For sRGB the 10-bit base is
   `min(C>>4,1023)`. For AdobeRGB it is `min(L[C]>>4,1023)`, using the original
   lookup at `0x53aa021c`. The package stores its exact 1024 lower thresholds
   instead of a floating-point approximation or a 16385-entry table.
4. For successive bases `a,b`, the original delta-record index is
   `d=clamp(b−a,0,240)`. Every one of the 241 original 64-bit delta records at
   `0x53aac900` expands to `floor(d*j/16)`, `j=0..15`. The 4096-entry response
   is therefore `a+floor(d*j/16)`; the last interval uses `d=0`.
5. The original packer `0x53135c60` copies these tables to the register image.
   CC0, YC and chroma suppression use the existing verified engine formulas.

Numerical source hashes and fixed state are recorded in
[`gold-tables.json`](../src/firmware_color_studio/data/k3iii/gold-tables.json).
Only numerical parameters are distributed; no firmware payload or decompiled
manufacturer code is included. This data is approximately 10.5 KB and does not
store a sweep of setting combinations.

## Corrected physical channel mapping

The upstream emulator's register labels are shifted. This is invisible for
ordinary modes with equal channel curves, but would render Gold as G/B/Y if
its old `CameraColour.from_tuning` selection were copied unchanged.

| Register image offset | Table aperture | Physical channel | Old harness key |
|---|---|---|---|
| `0x4768` | `0xaa00` | R | `rgb` |
| `0x4968` | `0xac00` | G | `r` |
| `0x4b68` | `0xae00` | B | `g` |
| `0x4d68` | `0xb000` | Yb | `b` |

The original register-application routine `0x532512cc` maps these image offsets
to these apertures; the upstream
[`verify_isp_configuration.py`](https://github.com/yunhyok/pentax-k3iii-firmware-analysis/blob/aa885bcdaee874d9b9bb18663dd62ed10263eda2/verify_isp_configuration.py)
executes that mapping. Independently, the public Milbeaut
[`im_r2y.h`](https://github.com/killsmm/m10v_mono/blob/main/ca7_rtos/target/cpu_tkernel/basefw/MILB_API/include/im_r2y.h)
names `AA00/AC00/AE00/B000` as `GMRFL/GMGFL/GMBFL/GMYBFL` in
`U_IM_R2Y_CTRL_RDMA_GMFL_TBL_VAL`. Gold always uses physical R/G/B and expands
the final integer response, including AdobeRGB remapping and delta limits.

## Preserving the zero-input table entry

The physical default RGB table entries at input zero are `[0, 0, 96]` in sRGB
mode and `[0, 0, 120]` in Adobe RGB mode, on the 0–1023 hardware scale. The
gamma evaluator must return those entries at zero. Its former multiplication
by `sign(input)` incorrectly replaced all three with zero and created an
artificial jump immediately above zero. The correction preserves zero-input
table values and mirrors only negative inputs used by the extension path.
Ordinary curves whose first entry is zero retain their existing zero response.
The [gamma endpoint tests](../tests/test_gold.py) cover zero, positive and
negative epsilon, both colour spaces, and an ordinary-mode zero control.

A fresh original-ARM Make check confirmed the first entries and all 12,288
physical RGB response entries per colour space at the nominal state. This is
the same read-only emulator boundary as the larger verification below, not ISP
pixel or camera execution. The [LUT fidelity evidence](lut-fidelity.md#two-distinct-corrections)
records this check and explains why the earlier Gold boundary reference had
to be corrected before measuring the separate DCP/XMP improvement.

## Runtime boundary

`runtime_spec()` returns `{}`; a nonempty runtime dictionary is rejected.
Nominal exposure gain is fixed to `0x2000`, denominator `0x2000`, project row
zero, Cross flag zero, Gold flag one, and setting override `+0x8d` zero.
The state accessor `0x53141a30` returns the singleton at `0x547bbe44`; its
`+0x33` custom-curve state is fixed to zero. No camera- or user-facing control
meaning for these internal state fields is claimed.

Original channel-preparation branch checks establish that nonzero `+0x33`
together with `+0x39` copies weighted Y into RGB. Setting `+0x8d` then replaces
RGB with 4096 while preserving Y. Nonzero `+0x33` also opens another downstream
lookup path using pointers at state `+0x0c/+0x10/+0x14`; this custom-state path
is outside the supported nominal model. Both mode flags set select Cross
before Gold; this control stops at Cross entry and does not evaluate a Cross
look. These paths are not exposed as guessed creative controls.

## Verification and reproduction

[`gold-verification.json`](../src/firmware_color_studio/data/k3iii/gold-verification.json)
records original ARM execution using Unicorn and an SHA-256-checked RTOS
payload. Whole Make comparisons cover 306 cases: both color spaces; default;
every slider independently across −4..+4; all 64 six-slider endpoint corners;
and 40 seeded mixed settings per space. All four final base tables, all packed
delta words, all expanded responses, CC0, YC and chroma parameters match
exactly. This does not exhaust all `9^6` setting combinations.

The verifier also executes the original register-application function and
compares all four physical full/difference SRAM tables. The upstream register
mapping verifier was rerun independently: eight synthetic groups, 312 checks
passed. Both use ordinary emulator memory in place of hardware registers.

Additional checks run the complete channel preparation including the original
getter for every unsigned 16-bit input (65,536), all 16,385 valid AdobeRGB lookup
inputs, every delta record, 134 original packing cases including decreasing
and saturated steps, and eight state/override combinations plus Cross priority.
Offline tests compare selected final tables to hashes recorded directly from
the original emulator output and cover signed interpolation and endpoints.

To reproduce, obtain the public
[`k3iii_tuning_emulator.py`](https://github.com/yunhyok/pentax-k3iii-firmware-analysis/blob/aa885bcdaee874d9b9bb18663dd62ed10263eda2/tools/k3iii_tuning_emulator.py)
at commit `aa885bcdaee874d9b9bb18663dd62ed10263eda2`, install the project's
verification dependencies (`numpy`, `unicorn`), and supply your decoded image:

```powershell
python tools/verify_gold.py C:/private/decoded.bin --harness C:/research/tools --output gold-check.json
python -m pytest tests/test_gold.py
```

The verifier reads the firmware and writes only the requested report. The
RTOS hash must be
`342d2f35405e8daf1797dfe431d2e4aa70f4b52a2c242a29df48206672f1dfb4`.
This verifies original configuration code and numerical table interpretation,
not execution of a camera ISP. Sensor processing, demosaicing, sharpening,
noise reduction, scene-dependent state and exact camera JPEG reproduction
remain outside this color model. No camera connection, firmware modification,
or hardware execution is performed.
