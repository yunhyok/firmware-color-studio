# Sources and third-party notices

Application code is MIT licensed. The application is independent research,
not affiliated with or endorsed by RICOH, PENTAX, or Adobe.

## Firmware-derived research

The color engine, DCP builder, color model, published color tables and default
profiles originate in Yunhyok's [PENTAX K-3 Mark III firmware research](https://github.com/yunhyok/pentax-k3iii-firmware-analysis),
revision `aa885bcdaee874d9b9bb18663dd62ed10263eda2`, firmware 2.20.
Source hashes and changes are recorded in the camera pack manifest. The
MIT license on application code does not assert ownership of RICOH's firmware
or independently relicense manufacturer-derived numerical data. The research
owner has authorized reuse of the already-published numerical tables here.
No original firmware image or decompiled manufacturer code is distributed.

The original calibration row scales are from the metadata of a reference
camera, not a RAW/JPEG fit. Users can import their own K-3 III DNG calibration.

The PENTAX Q7 pack's numerical tables (`data/q7/q7-color-tables.json`) were read from
firmware 1.01 for this project and for Yunhyok's
[PENTAX Q7 firmware research](https://github.com/yunhyok/pentax-q7-firmware-analysis); the same
terms apply. The manifest records the firmware and table hashes. The meaning of the Q7 maker
note tags that hold a shot's settings follows the tag table of
[ExifTool](https://exiftool.org/TagNames/Pentax.html) by Phil Harvey; no ExifTool code is included.

## Built-in looks of other cameras

`data/looks/chart-looks.json` holds, for six cameras (Kodak C875, Sony DSC-P200, DSC-TX66 and DSC-T100, Konica
Minolta DiMAGE X1, Samsung EX1), the 24 patch colours measured in one JPEG that each camera took of a
ColorChecker Classic. The photographs are Yunhyok's and are not distributed. The looks are estimates from those
measurements, not profiles made or approved by the cameras' manufacturers; the names only say which camera took
the photograph.

## ColorChecker reference measurements

The JPEG chart feature uses the D50/2° numerical reference measurements published by X-Rite for the ColorChecker Classic before November 2014 and from November 2014 onward. ColorChecker is a trademark of its owner. The app includes the reference numbers in patch order. X-Rite chart artwork and example JPEGs are not bundled. [Manufacturer’s edition notes](https://www.xrite.com/en/service-support/new_color_specifications_for_colorchecker_sg_and_classic_charts) · [X-Rite reference data archive](https://doi.org/10.5281/zenodo.3245895)

## Runtime dependencies

- Automatic chart recognition uses OpenCV 4.11.0 and the MCC module by Pedro Diamel Marrero Fernández. The installer includes the wheel's notices under `_internal/cv2` and the MCC module's MIT license under `resources/licenses/OpenCV`. [OpenCV license](https://github.com/opencv/opencv/blob/4.11.0/LICENSE) · [MCC source and license](https://github.com/opencv/opencv_contrib/blob/4.11.0/modules/mcc/include/opencv2/mcc/checker_detector.hpp) · [Wheel distribution](https://pypi.org/project/opencv-contrib-python-headless/4.11.0.86/)

- NumPy 1.26.4 uses BSD-3-Clause. The wheel's license also lists its bundled
  libraries. [NumPy source and license](https://github.com/numpy/numpy/tree/v1.26.4)
- Qt, PySide6 and Shiboken 6.8.3 are distributed under LGPLv3. The installer
  includes copies of the LGPLv3 and GPLv3 texts. [Qt license texts](https://github.com/qt/qtbase/tree/v6.8.3/LICENSES) · [Qt third-party notices](https://doc.qt.io/qt-6.8/licenses-used-in-qt.html) · [PySide third-party notices](https://doc.qt.io/qtforpython-6.8/licenses.html)
- rawpy 0.28.0 uses MIT. The bundle distributes LibRaw 0.22.2 under LGPL 2.1
  and includes the wheel's license text and the upstream copyright notice.
  [rawpy licenses and build source](https://github.com/letmaik/rawpy/tree/v0.28.0) · [LibRaw copyright notice](https://github.com/LibRaw/LibRaw/blob/0.22.2/COPYRIGHT)
- The rawpy Windows build uses vcpkg 2026.07.29 for zlib 1.3.2,
  libjpeg-turbo 3.2.0, JasPer 4.2.9 and Little CMS 2.19.1. Copies of the
  upstream notices are under `licenses/rawpy`.
  [Windows build recipe](https://github.com/letmaik/rawpy/blob/v0.28.0/.github/scripts/build-windows.ps1) · [vcpkg ports](https://github.com/microsoft/vcpkg/tree/2026.07.29/ports) · [zlib license](https://github.com/madler/zlib/blob/v1.3.2/LICENSE) · [libjpeg-turbo licenses](https://github.com/libjpeg-turbo/libjpeg-turbo/blob/3.2.0/LICENSE.md) · [JasPer license](https://github.com/jasper-software/jasper/blob/version-4.2.9/LICENSE.txt) · [Little CMS license](https://github.com/mm2/Little-CMS/blob/lcms2.19.1/LICENSE)
- Python uses the Python Software Foundation license.
  [Python 3.12 license](https://docs.python.org/3.12/license.html)
- PyInstaller 6.21.0 uses GPL with a bootloader distribution exception.
  [PyInstaller license and exception](https://pyinstaller.org/en/v6.21.0/license.html)

### Corresponding source and library replacement

Corresponding library source is available without charge at the following
version-specific links.

- [Qt 6.8.3 source archive](https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz)
- [PySide6 and Shiboken 6.8.3 source archive](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/pyside-setup-everywhere-src-6.8.3.tar.xz)
- [LibRaw 0.22.2 source archive](https://www.libraw.org/data/LibRaw-0.22.2.tar.gz) · [rawpy v0.28.0 build source and pinned submodules](https://github.com/letmaik/rawpy/tree/v0.28.0)

Qt, PySide6, Shiboken and LibRaw are dynamically loaded from the installed
application's `_internal` folder. To use your compatible modified library,
close the application, replace the matching DLL or Python extension in that
folder, and relaunch it. The applicable LGPL terms allow reverse engineering
the application to debug your modifications to those libraries.

Release preparation runs `tools/release_resources.py` using the pinned
environment. The script verifies the checked-in upstream texts and collects
the wheel notices and Python license, which the installer includes under
`_internal/firmware_color_studio/resources/licenses`.

## Adobe interoperability

This product includes DNG technology under license by Adobe.
The DNG format and enhanced profiles are implemented using the
[Adobe DNG specification and Profiles SDK](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html).
Adobe SDK source is not bundled in the application. The independent preview
implements a bounded reference processing path; it is not Adobe Camera Raw
or Lightroom, and does not claim pixel identity with those applications.

## Demo photograph

The bundled color cube RAW is Terry Duell’s PENTAX K-3 Mark III photograph,
published as raw.pixls.us sample 4678 under CC0 1.0. The bundle contains the
original DNG bytes.
[Source DNG](https://raw.pixls.us/getfile.php/4678/nice/Pentax%20-%20K-3%20Mark%20III%20-%2014bit%20%283%3A2%29.DNG) · [Source EXIF](https://raw.pixls.us/getfile.php/4678/exif/_IMG0114.DNG.exif.txt) · [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
