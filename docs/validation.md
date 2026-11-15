# Validation and limits

This page distinguishes checks of original firmware code, application behavior and Adobe compatibility. Passing a numerical test does not establish pixel-identical camera JPEG output.

## Firmware and data

- Sixteen default DCP templates and the ordinary engine table file are checked against the pinned upstream SHA-256 manifest. Exported bilingual names change the name tag only; regression tests compare the unchanged payload bytes.
- Gold's nominal-state implementation matches 306 original ARM tuning executions, including both color spaces, each control across −4…+4, 64 endpoint combinations and seeded mixed settings. All 65,536 channel-preparation inputs, 16,385 AdobeRGB conversion inputs and 241 packed delta records were also checked. [Detailed evidence](../src/firmware_color_studio/data/k3iii/gold-verification.json)
- This is static/emulated configuration evidence. No camera connection, firmware installation or physical ISP execution was performed.

## Application

The test suite covers recipe validation, source hashes, numeric output, DCP parsing/encoding, XMP binary encoding and interpolation, Gold response, RAW black/white levels, WB, CFA, crop, orientation, calibration identity and GUI export safety. Synthetic tests include unsupported/malformed input rejection. Real pre-existing K-3 III DNG and PEF files were decoded read-only and retained their original SHA-256 hashes.

The developer checks also reproduced an installed Adobe XMP table's serialized bytes and MD5 fingerprint. This confirms the stream format; it is separate from Lightroom importing and rendering a generated profile.

## Fidelity boundary

The standard renderer models the exported DCP. The enhanced renderer models its neutral DCP plus quantized 32³ RGB LUT, including Adobe's exposure and tone ordering. It does not emulate Lightroom's complete process version, demosaicing, sharpening, noise reduction, lens corrections, local edits or scene-dependent camera processing.

LUT sampling can cause substantial local errors near channel clipping and highly saturated colors. A deterministic Gold/AdobeRGB sensor sample `[0.7850411286, 0.7747761263, 0.2027623889]` at zero total exposure yields direct firmware-model sRGB `[0.93533, 0.95104, 0]`, while the exported LUT gives approximately `[0.93508, 0.94951, 0.23191]`. The blue-channel difference is about **59/255**, even though this sample's ProPhoto components lie within 0.05…0.95. Lower mean and percentile error over selected samples does not bound these worst cases. Gold and tinted enhanced profiles should be judged with representative photographs; no photo-derived correction is applied.

The nominal Gold model rejects unknown runtime overrides. Its fixed state and unresolved branches are documented in [gold.md](gold.md). Full camera JPEG equivalence and every one of the `9^6` control combinations remain unverified.
