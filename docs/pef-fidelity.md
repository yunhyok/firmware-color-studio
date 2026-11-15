# K-3 Mark III PEF preview exposure

The PEF preview uses −0.3 EV before applying the exported profile and caps the MakerNote white level at 16,315. A lower MakerNote white level remains in effect. Adobe DNG Converter 18.7 wrote exactly `BaselineExposure = -3/10` when converting the test PEF to a lossless CFA DNG. The firmware calculation gives −0.506243 EV for the same capture. Firmware Color Studio records the firmware estimate and original white level in `firmware_baseline_exposure` and `maker_note_white_level`. The preview uses `baseline_exposure` and `white_level`, each with its provenance in the RAW metadata. Native DNG previews read both values from the file. [Adobe DNG specification and SDK](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html) · [K-3 Mark III firmware exposure calculation](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/firmware-color-pipeline.html#gamma)

## Where the exposure values enter

The firmware stores one quarter of its exposure gain in PEF MakerNote tag `0x009d`. Routine `0x53127888` uses this gain with the sensor range to compute the baseline written to a camera DNG. Adobe defines DNG `BaselineExposure` as an offset to the raw converter’s exposure zero point. In Adobe DNG SDK 1.7.1, `dng_negative::TotalBaselineExposure` adds the selected profile’s `BaselineExposureOffset` to the input baseline. `dng_render_task` uses the total when building its exposure ramp and tone curve. The Natural DCP used here contributed +0.5 EV. At an Exposure slider value of 0 EV, the input and profile baseline terms sum to −0.006243 EV for the firmware calculation and +0.2 EV for the Adobe conversion. [Adobe DNG SDK](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html) · [Firmware DCP profile design](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/firmware-dcp.html)

The SDK sets its camera white point from the DNG neutral and forms its camera-to-working-space transform from the profile’s CameraToPCS and the ProPhoto RGB conversion from the D50 profile connection space. The converter DNG records unit AnalogBalance and omits camera calibration matrices. The Natural DCP has identical A and D65 ForwardMatrices. Together with the paired gain comparison below, these observations support the existing white balance and profile transform for this correction. [Adobe DNG SDK](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html) · [K-3 Mark III as-shot neutral comparison](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/lightroom-pef-neutral.html)

## Same-frame controls

The original PEF and the lossless conversion decoded to identical 4224×6304 CFA arrays. The active area starts at sensor coordinates (left 26, top 34). The 6192×4128 crop starts at (28, 24) within that area. Both files record black level 64. The maximum difference between the green-normalized MakerNote gain and the reciprocal Adobe `AsShotNeutral` gain was 1.095×10⁻⁶. At equal white levels, the decoded half-resolution camera RGB arrays agreed within 5.37×10⁻⁷. The DNG stored a white level of 16,315 and the PEF stored 16,378. The equal CFA samples show that the converter preserved the stored raster. [CFA comparison](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/lightroom-cfa-preservation.html) · [As-shot neutral evidence](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/lightroom-pef-neutral.html)

Seven converter runs used the same CFA raster. One copied the original metadata. The others independently changed reported ISO from 100 to 400 or 6400, the MakerNote gain tag from 2048 to 1024 or 4096, the MakerNote white level from 16,378 to 16,000, or the black level from 64 to 128. All seven output DNGs recorded exactly −3/10 EV. The changed white-level control produced a white level of 16,000. The changed black-level control produced a black level of 128 and a white level of 16,315. Three additional controls changed MakerNote white to 16,314, 16,315, and 16,316. The resulting DNG white levels were 16,314, 16,315, and 16,315. All ten controls used one physical capture. The ISO edits tested how the converter reads metadata and left the original CFA bytes and sensor response intact. [Converter control evidence](pef-fidelity-evidence.json) · [MakerNote ISO tag definition](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Pentax.pm#L1474)

## Lightroom comparison

Lightroom Classic 16.0 exported the native PEF and its lossless conversion with the same Natural DCP, As Shot white balance, and an Exposure slider value of 0 EV. Both TIFFs showed the same profile digest and identical values in all 2,001,000 16-bit channel samples. This connects the converter metadata to the observed Lightroom rendering for this capture. [Paired Lightroom and converter evidence](pef-fidelity-evidence.json)

The preview comparison uses direct pixel coordinates in 1000×667 images. Errors are absolute differences between normalized sRGB channel values. The exposure choices and white levels come from the files or the firmware calculation. The test held the profile settings fixed and used the original placement of each image. [Comparison evidence](pef-fidelity-evidence.json)

| Offline input | Mean absolute error | 95th percentile error |
| --- | ---: | ---: |
| Firmware baseline and native PEF white level | 0.028508 | 0.046354 |
| Firmware baseline and converted DNG white level | 0.027673 | 0.045434 |
| Adobe baseline and native PEF white level | 0.010006 | 0.031522 |
| Adobe baseline and capped PEF white level (current preview) | 0.010473 | 0.032212 |
| Converted DNG CFA and all its input tags | 0.010473 | 0.032212 |

The selected policy follows the observed Adobe converter settings and paired Lightroom result. The uncapped trial has a slightly lower MAE for this frame while using a different saturation level from the Lightroom-equivalent conversion. The PEF preview reads its per-channel black levels and as-shot gains from the camera file. [PEF fidelity evidence](pef-fidelity-evidence.json)

## Remaining preview differences

The runtime forms one RGB pixel per 2×2 Bayer tile before area resizing. The Adobe DNG SDK 1.7.1 sample renderer uses bicubic resampling of its Stage 3 demosaiced image at the requested size before camera-to-working-space conversion. Substituting the SDK’s full Stage 3 dump for the app’s Bayer rectangles, with the app’s area resizer and the same DCP, reduced MAE to 0.009341 and the 95th percentile error to 0.028636. Applying white balance after the app’s area resize while retaining the half-resolution Bayer image gave 0.010483 and 0.032228. The remaining difference spans stages outside these controls. [SDK Stage 3 experiment](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/lightroom-sdk-stage3.html) · [Adobe DNG SDK](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html)

