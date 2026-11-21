# Firmware Color Studio

**PENTAX K-3 Mark III**와 **PENTAX Q7**용 Lightroom 프로파일을 만들고 RAW에 적용해 비교하는 Windows 앱입니다. 카메라 모드는 각 카메라의 펌웨어(K-3 Mark III 2.20, Q7 1.01)에서 확인한 수식과 표로 재현합니다. **차트 JPEG → DCP**에서는 다른 카메라로 촬영한 ColorChecker Classic 사진 한 장을 이용해 색감을 추정합니다.

[Windows 설치 파일](https://github.com/yunhyok/firmware-color-studio/releases/latest) · [계산 근거](docs/architecture.md) · [Q7 지원 범위와 한계](docs/q7.md) · [Gold 분석](docs/gold.md) · [XMP 방식과 한계](docs/enhanced.md)

## 사용 방법

**다른 카메라의 JPEG 색감을 가져오려면** 상단의 **차트 JPEG → DCP**를 누르거나 JPEG를 창에 끌어 놓으세요. Studio가 ColorChecker Classic의 위치와 방향을 찾아 24개 패치에 번호를 표시하고 색감을 추정합니다. 번호와 미리보기를 확인한 뒤 **DCP 저장**을 누르세요. 자동 인식에 실패했을 때만 바깥 네 모서리를 지정해 달라는 안내가 나타납니다. 모서리는 어떤 순서로 눌러도 인쇄된 색 배열로 방향을 맞추며, 네 번째 모서리를 누르면 색감 추정이 자동으로 끝납니다. [지원 차트·사용법·검증 결과](docs/chart-profiles.md)

**차트 사진 없이 다른 카메라의 색감을 쓰려면** 상단의 **다른 카메라 색감**을 누르세요. Kodak C875, Sony DSC-P200·TX66·T100, Konica Minolta DiMAGE X1, Samsung EX1의 색감이 들어 있고, 고르면 선택한 카메라용 DCP를 만듭니다. 각 카메라가 같은 ColorChecker를 찍은 JPEG 한 장에서 잰 값이며 제조사의 프로파일이 아닙니다. [내장 색감](docs/chart-profiles.md#built-in-looks)

**펌웨어 카메라 모드와 RAW 비교**

1. Releases의 `FirmwareColorStudio-…-windows-x64-setup.exe`를 실행합니다. Python이나 카메라 펌웨어 파일을 따로 설치할 필요가 없습니다.
2. 파일을 지정하지 않고 시작하면 CC0 컬러 큐브 DNG를 자동으로 엽니다. 다른 K-3 III PEF/DNG나 Q7 DNG를 열거나 끌어 놓을 수 있습니다. 왼쪽에서 프로파일을 선택하면 비교 기준과 현재 설정을 나란히 표시합니다.
3. 채도, 색상, 밝기(Key), 대비, 하이라이트/섀도 대비를 −4…+4에서 조정합니다. **촬영 설정 가져오기**는 RAW의 지원되는 Custom Image 설정을 가져옵니다. **출고값으로 복원**은 선택 모드의 기본값으로 돌아갑니다.
4. 일반 모드는 DCP를 내보냅니다. Gold 또는 조색을 선택하면 **DCP + XMP (ZIP)**으로 전환되고, 일반 모드로 돌아오면 DCP로 복귀합니다. 직접 고른 ZIP 형식은 유지됩니다. 레시피 JSON은 나중에 열어 수정할 수 있습니다.
5. Lightroom의 현상 모듈에서 프로파일 탐색기의 **프로파일 가져오기**로 DCP 또는 ZIP을 가져옵니다. 수동 설치 시 DCP는 `%APPDATA%\Adobe\CameraRaw\CameraProfiles`, XMP는 `%APPDATA%\Adobe\CameraRaw\Settings`에 넣고 Lightroom을 다시 실행합니다. XMP에는 짝이 되는 base DCP가 필요합니다. ZIP 안의 파일 이름은 프로파일마다 달라 여러 묶음을 같은 폴더에 풀어도 서로 덮어쓰지 않습니다. [Adobe 안내](https://helpx.adobe.com/lightroom-classic/help/develop-module-options.html)

앱 언어와 관계없이 프로파일의 영문·한글 이름을 함께 표시합니다. 내보낸 DCP/XMP 이름도 같습니다. 일반 모드의 한글 표기는 [K-3 III 한국어 설명서](https://www.saeki.co.kr/cs/reference/detail?bbsClCd=CS112004&bbspstId=893)를 따르며, 후속 특별 모드는 음역을 사용합니다.

| 기본 DCP | 추가 지원 |
|---|---|
| Natural (자연스럽게), Bright (선명하게), Portrait (인물), Landscape (풍경) | Gold (골드): DCP + XMP |
| Vibrant (강렬 색감), Radiant (팝튠), Muted (은은하게), Flat (플랫) | Bleach Bypass 등 지원 모드의 8가지 조색: DCP + XMP |
| Bleach Bypass (블리치 바이패스), Reversal Film (리버설 필름), Monochrome (모노톤) | 카메라 sRGB/Adobe RGB 설정, 사용자 DNG 보정 행렬 |
| SATOBI (사토비), HARUBENI (하루베니), KATEN (카텐), KYUSHU (큐슈), FUYUNO (후유노) | 설정 JSON 저장·불러오기, 커스텀 이름 |

**PENTAX Q7 프로파일**

상단의 카메라 메뉴에서 **PENTAX Q7**을 고르면 Q7 펌웨어 1.01의 Custom Image 10종으로 바뀝니다: Natural, Bright, Portrait, Landscape, Vibrant, Radiant, Muted, Bleach Bypass, Reversal Film, Monochrome. 조절 항목은 펌웨어를 따릅니다. Q7에는 하이라이트/섀도 대비가 없고, Muted와 Bleach Bypass는 색상 대신 조색을 씁니다. 내보낸 DCP의 카메라 이름은 `PENTAX Q7`이므로 Lightroom에서 Q7 DNG에만 나타납니다.

- 색 행렬·감마·YC 계산과 카메라가 실제로 보간하는 9×9×9 3차원 표는 Q7 펌웨어 루틴을 CPU 에뮬레이터로 실행한 결과와 모든 설정에서 일치합니다.
- ColorChecker를 찍은 Q7 DNG 한 장을 카메라에서 Custom Image 10종으로 현상한 JPEG과 비교하면, 기록된 설정으로 만든 프로파일의 24패치 평균 색차는 ΔE76 1.0~1.4입니다. 전체 밝기 기준(`BaselineExposureOffset` +0.5 EV)도 이 사진으로 맞췄습니다. 다른 감도와 Lightroom 출력은 비교하지 않았습니다.
- Q7 DNG를 열면 카메라가 Q7로 바뀌고, 촬영 설정 가져오기와 DNG 보정 행렬 가져오기도 Q7 파일에서 동작합니다. 다른 카메라의 RAW를 연 상태의 미리보기는 두 카메라의 센서 행렬로 환산한 근사입니다. [Q7 지원 범위와 한계](docs/q7.md)

## 지원 범위

- 일반 컬러 K-3 III의 14-bit 단일 프레임 Bayer PEF 및 원본 DNG, Q7의 원본 DNG를 지원합니다. Pixel Shift, HDR, K-3 III Monochrome과 변환된 DNG의 미리보기는 지원하지 않습니다.
- 미리보기는 RAW의 블랙 레벨, 화이트 레벨, 촬영 화이트밸런스, Bayer 패턴, 기본 크롭과 방향을 반영하는 ½ 해상도 색 비교입니다. 조정 중에는 긴 변 480px, 멈추면 1000px로 갱신합니다. 모니터 ICC를 적용합니다.
- PEF는 Adobe 변환 메타데이터에서 확인한 기준 노출 −0.3 EV와 화이트 레벨 상한 16,315를 미리보기에 적용합니다. 같은 촬영의 원본 PEF와 무손실 변환 DNG를 Lightroom에서 내보내 비교했습니다. 카메라 원본 DNG는 파일의 기준 노출과 화이트 레벨을 읽습니다. [PEF 보정 근거](docs/pef-fidelity.md)
- 샤프니스, 노이즈 감소, 렌즈 보정 및 Lightroom 전체 현상 파이프라인을 복제하지 않습니다. 따라서 카메라 JPEG 또는 Lightroom 출력과 픽셀 단위로 같다는 뜻은 아닙니다.
- 16개 기본 DCP는 공개 연구의 수치 데이터를 보존하며 이름 태그만 한글 병기로 바꿉니다. Gold 정수 표는 원본 ARM 코드 실행과 비교했습니다. 향상 프로파일은 펌웨어 CC0 행렬을 담은 base DCP와 32³ RGB LUT를 담은 XMP를 함께 사용합니다. 고채도와 클리핑 경계의 오차는 따로 측정했습니다. [검증 범위](docs/validation.md) · [v0.1.4의 32³ LUT 경계 보정과 검증 수치](docs/enhanced.md#v014-chroma-suppression-boundaries)
- Gold의 알려진 명목 상태를 사용합니다. 의미가 확인되지 않은 내부 런타임 플래그는 사용자 조절 항목으로 만들지 않았습니다. [분석 및 미해결 경계](docs/gold.md#runtime-boundary)

## 개발·빌드

Windows x64, Python 3.12, Inno Setup 6:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m firmware_color_studio
.\.venv\Scripts\python -m pytest -q
./tools/build_windows.ps1
```

CLI는 `fcs verify --report result.json`, `fcs recipe recipe.json --camera pentax-q7 --mode bright`(출고값 레시피 쓰기), `fcs export recipe.json output.dcp`, `fcs export recipe.json output.zip --enhanced`, `fcs preview input.DNG output.png --mode natural`을 제공합니다. `--camera`는 `pentax-k3iii`(기본) 또는 `pentax-q7`이며, `fcs preview`는 생략하면 RAW를 찍은 카메라를 씁니다. CLI 출력 파일은 기존 파일을 덮어쓰지 않습니다.

차트 사진에는 `fcs chart-fit`을, 내장 색감에는 `fcs look`을 사용합니다. [자동 인식과 수동 좌표 사용 예제](docs/chart-profiles.md#cli)

## 출처와 라이선스

이 앱은 [pentax-k3iii-firmware-analysis](https://github.com/yunhyok/pentax-k3iii-firmware-analysis)의 `aa885bcdaee874d9b9bb18663dd62ed10263eda2` 연구를 기준으로 구현했습니다. Q7 팩의 수치는 [pentax-q7-firmware-analysis](https://github.com/yunhyok/pentax-q7-firmware-analysis)와 이 저장소의 [연구 기록](docs/research/q7-port.md)에서 나왔습니다. 배포 패키지는 Terry Duell의 컬러 큐브 원본 DNG 한 장을 CC0 1.0으로 포함합니다. 데모의 출처와 해시는 별도 기록에서 확인할 수 있습니다. 패키지에 펌웨어, Adobe SDK 또는 제조사 코드의 디컴파일 결과를 포함하지 않습니다. [데모 출처와 라이선스](src/firmware_color_studio/data/demo/README.md) · [카메라 데이터 출처와 SHA-256](src/firmware_color_studio/data/k3iii/manifest.json)

앱 코드는 MIT입니다. 외부 라이브러리 및 수치 데이터의 출처는 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)를 확인하십시오. PENTAX/RICOH 및 Adobe와 제휴하거나 공식 인증받은 소프트웨어가 아닙니다.

---

**English:** An offline Windows editor for K-3 III camera profiles. Create a Lightroom DCP from another camera’s ColorChecker Classic JPEG using **Chart JPEG → DCP**. The separate firmware tools export 16 standard DCPs and enhanced XMP bundles for tinting and Gold. The app previews PEF/DNG files and opens a bundled CC0 color cube DNG at startup.
