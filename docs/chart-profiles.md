# JPEG 차트로 Lightroom 프로파일 만들기

다른 카메라의 JPEG에 담긴 색감과 명암을 추정해 **PENTAX K-3 Mark III용 단독 DCP**로 저장합니다. 원본 카메라의 RAW나 같은 장면을 찍은 Pentax RAW를 준비할 필요가 없습니다. 편집한 JPEG를 넣으면 편집이 반영된 색을 목표로 삼습니다.

## 차트 선택과 저장

1. **차트 JPEG → DCP**에서 JPEG를 엽니다. ColorChecker Classic 24 또는 ColorChecker Passport의 **6열 × 4행 Classic 면**을 사용하세요. 화면에 차트 전체가 보이고 패치에 반사광과 짙은 그림자가 적을수록 좋습니다. Digital SG, Video, Passport의 보정용 다른 면은 배열과 기준색이 다릅니다. [X-Rite 차트 구성](https://www.xritephoto.com/documents/literature/en/L11-293_ColorChecker_Targets_en.pdf)
2. **차트 제조 시기**를 선택합니다. 기본값은 2014년 11월 이후입니다. 촬영 날짜와 차트의 제조 시기는 다를 수 있습니다. X-Rite는 이 시점에 안료와 기준 측정값을 변경했습니다. [제조사 안내](https://www.xrite.com/en/service-support/new_color_specifications_for_colorchecker_sg_and_classic_charts)
3. JPEG를 열면 Studio가 차트의 위치와 방향을 찾아 1번부터 24번까지 표시하고 색감을 자동으로 추정합니다. 사진 위의 번호가 각 패치 중앙에 있는지 확인하세요. 비교표의 왼쪽은 JPEG 색, 오른쪽은 DCP 예측값입니다. 표시되는 평균 ΔE76은 피팅에 사용한 24개 패치의 색차입니다. Pentax RAW를 먼저 열었다면 **현재 Pentax RAW 미리보기**에서 결과를 볼 수 있습니다.
4. **자동 인식에 실패한 경우에만** 화면에 바깥 네 모서리를 지정하라는 안내가 나타납니다. 24패치가 인쇄된 차트 면의 **바깥 테두리**를 짙은 피부색 쪽 → 청록 쪽 → 검정 쪽 → 흰색 쪽 순서로 클릭하세요. Passport에서는 펼친 케이스 전체 중 Classic 면의 테두리를 사용하세요. 네 번째 모서리를 누르면 앱이 패치 사이 구분선을 찾아 24개 중심을 계산하고 색감을 추정합니다. 잘못 누른 점은 되돌릴 수 있습니다.
5. 기본 프로파일 이름은 JPEG EXIF의 촬영 기종입니다. 모델 표기와 제조사를 함께 사용하며, 촬영 기종 정보가 없으면 파일명을 사용합니다. 다른 조명이나 편집으로 만든 프로파일을 함께 사용할 때는 이름을 구분해서 저장하세요.
6. **DCP 저장** 후 Lightroom Classic 현상 모듈의 프로파일 브라우저에서 **프로파일 가져오기**를 선택합니다. K-3 III RAW를 열어 저장한 이름을 선택하세요. 다른 장면에 적용할 때는 노출과 화이트밸런스를 장면에 맞게 조절합니다. [Adobe 프로파일 사용 안내](https://helpx.adobe.com/lightroom-classic/desktop/process-and-develop-photos/image-tone-color.html)

## 계산 방식

앱은 JPEG의 EXIF 방향을 적용하고 내장 ICC로 sRGB로 변환합니다. ICC가 없는 RGB JPEG는 Adobe RGB EXIF가 있으면 해당 색공간을, 그 밖에는 sRGB를 사용합니다. 자동 인식 또는 수동 지정으로 얻은 네 점으로 원근 변환을 구하고, 각 패치 안쪽 81개 표본의 채널별 중앙값을 사용합니다. [JPEG 해석과 패치 추출](../src/firmware_color_studio/chart_input.py)

X-Rite의 D50 기준색과 K-3 III 카메라 행렬로 각 패치의 센서 입력을 추정합니다. 18% 회색의 밝기는 이 카메라의 기본 Natural 프로파일에서 구합니다. 이 기준을 고정한 뒤 회색 6개로 단조 톤 곡선을, 유채색 18개로 색상·채도·밝기 보정표를 계산합니다. 보정표는 인접 색상 사이에서 완만하게 변하도록 제한합니다. DCP를 직렬화한 뒤 다시 읽어 같은 패치에서 기준 프로파일과 비교하며, 평균 오차가 늘어날 때는 기준 프로파일을 사용합니다. [피팅 구현](../src/firmware_color_studio/chart_fit.py) · [X-Rite의 두 세대 기준값](https://doi.org/10.5281/zenodo.3245895) · [Adobe DNG 사양](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html)

## 자동 인식과 바깥 모서리 검증

v0.2.1은 OpenCV MCC로 Classic 24 후보를 찾습니다. 후보별로 인쇄된 배열의 방향, 회색 줄의 밝기 순서, 유채색의 순서, 패치 내부의 균일도를 확인합니다. 한 차트가 확실할 때만 자동으로 진행합니다. 수동 입력에서는 네 모서리의 원근을 보정하고 가로·세로 구분선 간격으로 실제 패치 위치를 계산하므로, 테두리가 넓은 차트도 같은 방식으로 지정할 수 있습니다. [OpenCV MCC의 차트 검출 API](https://github.com/opencv/opencv_contrib/blob/4.11.0/modules/mcc/include/opencv2/mcc/checker_detector.hpp) · [검출 코드](../src/firmware_color_studio/chart_detect.py)

v0.2.0에서 사람이 찍은 중심과 같은 JPEG에서 새로 찾은 위치를 비교했습니다. 아래 RGB 수치는 채널당 0~255 기준입니다. DCP 출력은 고정 난수 시드 761로 생성한 센서 RGB 1,024개를 두 DCP로 각각 현상해 비교했습니다.

| 기준 JPEG | 패치 측정 차이 평균 / 최대 | 피팅 평균 ΔE76 수동 → 자동 | DCP 출력 차이 평균 / 최대 |
|---|---:|---:|---:|
| Panasonic DMC-GF1 | 0.33 / 1 | 4.64 → 4.74 | 0.27 / 11.71 |
| OpenCV 실내 차트 | 0.22 / 1 | 5.84 → 5.87 | 0.22 / 16.26 |

두 JPEG의 회전·반전·원근·크기 변형에서도 패치 중심과 패치 측정값을 확인했습니다. 복수 차트 2건과 차트 없는 입력 9건은 자동 인식을 거부했습니다. OpenCV 사진의 임의 RGB 출력 최대 차이 16.26은 검증 기준 15를 초과했습니다. 패치 밖의 색에서는 프로파일 간 차이가 더 클 수 있습니다.

같은 Pentax PEF에서 얻은 1000 × 667 Lightroom 출력 2장에는 작은 실물 차트가 있습니다. 두 장 모두 자동 인식에 실패해 바깥 모서리를 지정했습니다. 이 두 장과 위 JPEG 두 장에서 각 기준점 지정과 여덟 차례 위치 변동을 비교한 36건 모두 패치를 올바르게 추출했습니다. 모서리 좌표를 JPEG에서 최대 ±3 px, 작은 차트에서 최대 ±1 px 움직였을 때 패치 평균 RGB 차이는 최대 0.31, 단일 채널의 최대 차이는 3이었습니다. 이 버전의 DCP 간 출력 차이는 Studio 렌더러에서 측정했습니다.

## 실물 차트 검증

아래 표는 v0.2.0에서 수동으로 지정한 위치를 기준으로 측정한 평균 ΔE76입니다. 값이 작을수록 기준 JPEG의 24색과 가깝습니다. 첫 번째 비교는 명목상 기준색에 대한 피팅이고, 두 번째 비교는 **별도로 촬영한 Pentax PEF 속 실물 차트**에 프로파일을 적용한 결과입니다. 모든 PEF 비교에서 촬영 화이트밸런스를 사용하고 노출 슬라이더를 0으로 유지했습니다. 두 JPEG 모두 이 PEF와 다른 촬영입니다. [좌표·해시·측정값](chart-validation.json)

| 기준 JPEG | 24패치 모델 오차, 보정 전 → 후 | 실물 PEF에서 색 보정 없는 기준 | 실물 PEF에서 Pentax Natural | 실물 PEF에서 생성 DCP |
|---|---:|---:|---:|---:|
| Panasonic DMC-GF1 | 9.85 → 4.64 | 11.22 | **9.36** | 10.20 |
| OpenCV 실내 차트 사진 | 16.09 → 5.84 | 18.34 | 18.20 | **8.15** |

Lightroom Classic 16.0에서도 같은 PEF를 두 가지 DCP로 현상해 1000 × 667, 16비트 sRGB TIFF를 내보냈습니다. TIFF 메타데이터에서 선택한 DCP 이름을 확인했습니다. Panasonic JPEG와의 실물 차트 오차는 생성 DCP에서 **10.89**, Pentax Natural에서 **9.71**이었습니다. 한 장의 JPEG에는 카메라 처리뿐 아니라 조명·노출·편집 결과도 남습니다. 이 예에서 Natural이 더 가까웠고, OpenCV 사진을 기준으로 한 앱 미리보기에서는 생성 DCP가 더 가까웠습니다. [Lightroom 출력 기록](chart-validation.json)

Panasonic 사진은 ColorScientist가 공개한 2010년 촬영본으로 EXIF에 Photoshop 편집 이력이 있습니다. OpenCV 사진은 촬영 기종 정보가 없어 파일명으로 내보냈으며 차트 세대는 기본값으로 가정했습니다. 검증 사진은 프로그램에 배포하지 않습니다. [Panasonic 촬영본](https://commons.wikimedia.org/wiki/File:ColorChecker100423.jpg) · [OpenCV 촬영본](https://github.com/opencv/opencv_extra/blob/ebf9366b3845efe1e54bf2440cf238fd68905bab/testdata/cv/mcc/mcc_ccm_test.jpg) · [검증용 Pentax PEF 기록](pef-fidelity.md)

## CLI

기본 명령은 JPEG에서 차트를 자동으로 찾습니다. `--edition pre2014`는 2014년 11월 이전에 제조한 차트에 사용합니다. `--name`을 생략하면 GUI와 동일한 규칙으로 이름을 정합니다.

```powershell
fcs chart-fit ColorChecker100423.jpg Panasonic.dcp --edition pre2014
```

자동 검출 실패 시 `--outer-corners`에 차트의 바깥 네 모서리를 같은 순서로 넣습니다. 좌표는 EXIF 방향을 적용한 JPEG의 픽셀 기준입니다. 아래 예는 Panasonic 검증 사진입니다.

```powershell
fcs chart-fit ColorChecker100423.jpg Panasonic-manual.dcp --edition pre2014 --outer-corners 31 24 1124 24 1124 813 31 813
```

v0.2.0 배치 작업의 `--corners`는 종전대로 네 **패치의 중심**을 받습니다. 두 옵션은 좌표의 의미가 다릅니다.
