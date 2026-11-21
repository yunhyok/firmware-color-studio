# Validation and limits

The evidence below covers firmware settings, application behavior and Lightroom rendering.

## Firmware and data

- Sixteen default DCP templates and the ordinary engine table file are checked against the pinned upstream SHA-256 manifest. Exported bilingual names change the name tag only; regression tests compare the unchanged payload bytes.
- Gold's nominal-state implementation matches 306 original ARM tuning executions, including both color spaces, each control across −4…+4, 64 endpoint combinations and seeded mixed settings. All 65,536 channel-preparation inputs, 16,385 AdobeRGB conversion inputs and 241 packed delta records were also checked. [Detailed evidence](../src/firmware_color_studio/data/k3iii/gold-verification.json)
- This is static/emulated configuration evidence. No camera connection, firmware installation or physical ISP execution was performed.

## Application

The test suite covers recipe validation, source hashes, numeric output, DCP parsing/encoding, XMP binary encoding and interpolation, Gold response, RAW black/white levels, WB, CFA, crop, orientation, calibration identity and GUI export safety. Synthetic tests include unsupported/malformed input rejection and a Q7 DNG with its own geometry and setting tags. Real pre-existing K-3 III DNG and PEF files and one Q7 DNG were decoded read-only and retained their original SHA-256 hashes.

The developer checks reproduced an installed Adobe XMP table’s serialized bytes and MD5 fingerprint. The application decodes the bundled CC0 color cube DNG at startup when no input file is specified. The verify command checks the sample’s SHA-256 and renders Natural and Bright. [Sample and license](../src/firmware_color_studio/data/demo/README.md)

## Camera JPEG comparison for v0.3.0

One ColorChecker Classic was photographed with a K-3 Mark III (firmware 2.12, DNG) and a Q7 (firmware 1.01, DNG). Each DNG holds the camera's own JPEG of the shot. Studio read the mosaic, took the Custom Image and its settings from the maker note, built that profile and rendered the 24 patches with the file's `BaselineExposure`. The table gives CIE 1976 colour differences between the rendering and the camera JPEG. [Hashes, coordinates and measurements](chart-session-validation.json) · [script](../tools/chart_session.py)

| DNG and profile | Mean ΔE76, 24 patches | 18 colours | 6 greys | Largest | Exposure at which the greys agree best |
|---|---:|---:|---:|---:|---:|
| K-3 Mark III, Landscape with saturation −1 | 2.25 | 2.80 | 0.61 | 9.59 (orange yellow) | 0.00 EV |
| Q7, Landscape at factory settings | 1.49 | 1.58 | 1.22 | 7.60 (yellow) | +0.06 EV |

On the K-3 Mark III file the profiles of other Custom Images differ from the JPEG by 3.10 (Bright) to 9.67 (Portrait); on the Q7 file by 3.90 to 11.57. The K-3 Mark III body ran firmware 2.12 and the pack follows 2.20; the grey patches show no exposure difference between them. Both JPEGs are the ones stored in the DNG (K-3 Mark III: full size; Q7: 1920 × 1280). This is one scene under one light, measured with Studio's DCP renderer; Lightroom was not run on these files. The same photographs test the chart profiles: [same-scene results](chart-profiles.md#same-scene).

## Lightroom Classic 16.0 boundary verification for v0.1.4

Lightroom loaded the v4 profiles on the bundled K-3 Mark III color-cube DNG and exported three 1000 × 667, 16-bit sRGB TIFFs. Each export used As Shot white balance and zero Develop exposure. The Lightroom SDK recorded the selected profile UUID before export. Each TIFF contained the expected base DCP name and RGB-table fingerprint, and all three pixel hashes differed. The photograph was used only after the table values were fixed. [Profile identities, TIFF hashes and measurements](lut-boundary-v4-lightroom.json)

| Profile and camera settings | Mean absolute difference | 95th percentile |
|---|---:|---:|
| HARUBENI (하루베니), Adobe RGB, tint 1, highlight contrast −4 | 0.005107 | 0.012020 |
| Gold (골드), Adobe RGB, mixed slider endpoints | 0.005427 | 0.016169 |
| FUYUNO (후유노), sRGB, default | 0.004030 | 0.007259 |

These differences compare the app preview with Lightroom at matching pixel coordinates in normalized 0–1 sRGB. The separate 32³ interpolation study compares synthetic RGB with the direct firmware formula and reports encoded channel errors on a 0–255 scale. [All ten regressions and the HARUBENI breakpoint](https://yunhyok.github.io/pentax-k3iii-firmware-analysis/analysis/gold-enhanced-profile.html#lut-v4)

## Historical Lightroom Classic 16.0 validation for v0.1.0

Lightroom Classic 16.0 exported TIFFs for all 21 v0.1.0 cases: the 16 default DCPs, two customized DCPs, Gold, green-toned Bleach Bypass, and Natural on a PEF. Each output was a 1000×667, 16-bit RGB TIFF with an sRGB ICC. The 18 plain DNG outputs had distinct profile digests and pixel hashes. The enhanced outputs recorded the generated XMP UUID and RGB-table fingerprint, and their pixels differed from each other and from the plain outputs. Source RAW and isolated catalog preparation hashes were checked. [Machine-readable evidence](lightroom-validation.json)

The table reports absolute errors in normalized 0…1 encoded sRGB. It compares the v0.1.0 offline previews with the corresponding Lightroom exports at matching pixel coordinates, using fixed recipes and As Shot white balance. The campaign used two test photographs.

| Comparison | Mean absolute error | 95th percentile |
|---|---:|---:|
| DNG, 18 plain profiles | 0.00390–0.00696 | 0.00733–0.01601 |
| DNG, Gold | 0.00553 | 0.01628 |
| DNG, green Bleach Bypass | 0.00686 | 0.01608 |
| PEF, Natural | 0.02851 | 0.04635 |

## Lightroom Classic 16.0 enhanced profile validation for v0.1.3

Three newly exported v3 profiles were selected in Lightroom Classic's Profile Browser on the bundled K-3 III color cube DNG. Lightroom exported three 1000×667, 16-bit sRGB TIFFs. Each contained the expected DCP name and RGB table fingerprint. The three TIFF pixel hashes were distinct. The comparison used As Shot white balance, zero exposure-slider adjustment, and matching pixel coordinates. The image served only to check the completed profiles. [Recipes, hashes, export metadata and measurements](lut-boundary-lightroom.json)

| Recipe | Offline vs. Lightroom mean absolute error, normalized sRGB | p95 |
| --- | ---: | ---: |
| Gold, Adobe RGB | 0.005630 | 0.014639 |
| Muted, Adobe RGB, tint 1, key −4 | 0.004574 | 0.011154 |
| Bleach Bypass, sRGB, tint 1 | 0.005060 | 0.010493 |

The [synthetic boundary measurements](enhanced.md#preview-and-validation) compare interpolation against the firmware model over the sensor cube. The TIFF comparison measures the complete Adobe and offline renders on one photograph.

## Lightroom Classic 16.0 enhanced profile validation for v0.1.2

Lightroom Classic 16.0 exported 12 enhanced profiles from the same K-3 Mark III color cube DNG. The cases were Gold in both camera color spaces, green-toned Bleach Bypass, and HARUBENI at all nine toning values including 0. Each 1000×667 TIFF contained 16-bit RGB samples and an sRGB ICC profile. All 12 TIFF pixel hashes and RGB table fingerprints were distinct. TIFF XMP recorded four distinct base profile digests, with one shared by the nine HARUBENI variants. [Machine-readable evidence](lightroom-fidelity.json)

Each profile was selected in Lightroom’s Profile Browser and loaded once before the SDK batch export. In earlier SDK-only trials, some selections reverted or lacked RGB table settings. The successful batch retained the loaded Look and base profile before and after export, and TIFF XMP independently recorded the expected base profile and RGB table. [Machine-readable evidence](lightroom-fidelity.json)

The comparison below uses matching pixel coordinates, fixed generated recipes, As Shot white balance, and 0 EV on Lightroom’s Exposure slider. The offline renderer used the DNG’s stored baseline exposure. The values are absolute differences in normalized 0…1 encoded sRGB channels for this one DNG. [Comparison data](lightroom-fidelity.json)

| Enhanced profile | Cases | Mean absolute error | 95th percentile |
|---|---:|---:|---:|
| Gold, camera sRGB and Adobe RGB | 2 | 0.005635–0.005706 | 0.014908–0.015166 |
| Green-toned Bleach Bypass | 1 | 0.006879 | 0.015975 |
| HARUBENI, toning 0–8 | 9 | 0.005430–0.005435 | 0.011640–0.011645 |

## Plain profile validation in v0.1.2

The v0.1.2 Lightroom validation includes 16 exports, with four plain Natural cases alongside the 12 enhanced profiles. The camera DNG exported with both the stock bilingual profile name and a custom name. Those DCPs had the same numerical tag payloads, and the two TIFFs had identical pixels. Lightroom also exported the native PEF and its lossless converted DNG as a pair, with identical TIFF pixels. All four exports had the requested profile identity in TIFF XMP. [Machine-readable evidence](lightroom-fidelity.json)

Earlier SDK runs reverted to Adobe Standard for the camera DNG. The successful plain run used the refreshed Develop module and let the loaded profile settle before export. The converted DNG served as a Lightroom control. The three native-input previews were compared offline at the same coordinates and in the same normalized sRGB units as the enhanced tests. [Comparison data](lightroom-fidelity.json)

| Plain Natural input | Offline cases | Mean absolute error | 95th percentile |
|---|---:|---:|---:|
| Camera DNG, stock and custom profile name | 2 | 0.005890 | 0.011035 |
| Camera PEF | 1 | 0.010473 | 0.032212 |

## Current PEF preview

Adobe DNG Converter 18.7 recorded −0.3 EV for the K-3 Mark III PEF and capped its white level at 16,315. Metadata controls on copies of one capture reproduced the same baseline with altered ISO, gain, white and black tags. In Lightroom Classic 16.0, the native PEF and the lossless converted DNG exported with the same Natural DCP had identical values in all 2,001,000 16-bit channel samples. [PEF analysis](pef-fidelity.md) · [Machine-readable evidence](pef-fidelity-evidence.json)

The current offline PEF preview uses this Adobe baseline and cap. Its Natural error against the paired Lightroom TIFF is 0.01047 mean and 0.03221 at the 95th percentile. The application retains the firmware-derived exposure and original MakerNote white level as separate fields. The standalone renderer comparison covers the one capture and the settings listed in the PEF analysis. [Comparison details](pef-fidelity.md#lightroom-comparison)

## Fidelity boundary

The standard renderer models the exported DCP. The enhanced renderer models its CC0 base DCP and quantized 32³ RGB LUT, including the Adobe exposure and tone ordering used for the profile. The comparison covers color and tone. Lightroom demosaicing, sharpening, noise reduction, lens correction and local edits can affect the output.

The v0.1.0 direct model forced the zero-input gamma to zero, invalidating its reported Gold blue-channel boundary difference of 59/255. At input zero the firmware gamma takes the first table entry. The physical blue code at that entry is 96 for sRGB and 120 for Adobe RGB. LUT sampling still contributes error near clipping and at high saturation. [Zero-input regression](../tests/test_gold.py) · [Corrected LUT analysis](lut-fidelity.md)

The nominal Gold model rejects unknown runtime overrides. Its fixed state and unresolved branches are documented in [gold.md](gold.md). Full camera JPEG equivalence and every one of the `9^6` control combinations remain unverified.
