# RTSPStreamer

영상 파일 또는 웹캠을 선택하면 FFmpeg와 MediaMTX를 이용해 Windows에서 RTSP
스트림으로 송출하고, 시간표에 맞춰 수위값을 DB에 INSERT하는 GUI 프로그램입니다.

기본 송출 및 재생 주소:

```text
rtsp://127.0.0.1:8554/live/stream
```

## 주요 기능

- MP4, AVI, MKV, MOV, WMV, WebM, TS 영상 지원
- PC에 연결된 웹캠 DirectShow 장치 송출 지원
- 웹캠 선택 시 작은 라이브 미리보기 표시
- 영상 무한 반복 송출
- H.264 영상 및 AAC 오디오 송출
- 내장 MediaMTX RTSP 서버 자동 실행
- 영상 길이 자동 인식 후 초/분 단위 시간표 생성
- 엑셀에서 복사한 수위값 여러 행 붙여넣기 지원
- 표에서 Ctrl+C / Ctrl+X / Ctrl+V 단축키 지원
- CSV/Excel 수위값 파일 불러오기 및 드래그앤드롭 지원
- 작업 설정 저장/불러오기 및 최근 설정 바로 불러오기 지원
- 송출 중 현재 시각 기준 PostgreSQL DB INSERT
- FFmpeg 및 서버 오류를 GUI로 표시
- Python이 설치되지 않은 Windows PC용 실행 파일 빌드 지원

## 개발 환경에서 실행

프로젝트 루트에 다음 실행 파일을 준비합니다.

- `ffmpeg.exe`
- `mediamtx.exe`

그다음 가상환경에서 실행합니다.

```powershell
python main.py
```

## Windows 배포판 빌드

프로젝트 루트에 `ffmpeg.exe`, `mediamtx.exe`, `mediamtx.yml`이 있는지 확인한 후:

```powershell
.\build.ps1
```

완성된 배포판은 `dist\RTSPStreamer`에 생성됩니다. 배포할 때는 EXE만 보내지
말고 `RTSPStreamer` 폴더 전체를 ZIP으로 압축해야 합니다.

## 사용 방법

1. `RTSPStreamer.exe`를 실행합니다.
2. 입력 소스를 선택합니다.
   - **영상 파일**: 송출할 파일을 선택합니다.
   - **웹캠**: 목록에서 웹캠을 선택합니다. 장치가 안 보이면 **웹캠 새로고침**을 누릅니다.
     선택한 웹캠 화면은 작은 미리보기로 바로 확인할 수 있습니다.
3. 시간표 간격을 초/분 단위로 설정합니다.
4. 수위값을 직접 입력하거나 엑셀에서 복사해 붙여넣습니다.
   또는 CSV/Excel 파일을 불러오거나 표에 드래그앤드롭합니다.
   파일 제목 행은 **파일 첫 행 건너뛰기**, 표의 `00:00` 행은
   **표 첫 행 건너뛰기** 옵션으로 제외할 수 있습니다.
5. PostgreSQL DB명, 사용자명, 암호, host, port, 스키마, 테이블명, 컬럼명을 확인합니다.
6. 필요하면 **설정 저장**으로 현재 영상/RTSP/DB/시간표 값을 JSON 파일로 저장합니다.
7. RTSP 주소를 확인하고 **송출 시작**을 누릅니다.
8. VLC 등의 플레이어에서 같은 RTSP 주소를 엽니다.

저장한 설정은 **설정 불러오기**로 다시 열 수 있으며, 최근에 불러온 설정은
우측 상단의 **최근 설정** 목록에서 바로 선택할 수 있습니다.

웹캠 모드에서는 실시간 입력이라 영상 길이를 알 수 없습니다. 이때 표의 시간은
`영상 시간`이 아니라 `송출 시작 후 경과시간`입니다. 예를 들어 `00:10` 행의 값은
송출 시작 10초 뒤 현재시간과 함께 INSERT됩니다. 수위파일을 불러오면 값 개수만큼
경과시간표가 자동 생성되고, 표에 입력된 수위값을 한 번 순서대로 INSERT합니다.
영상 파일 모드는 기존처럼 영상 시간과 영상 반복에 맞춰 DB INSERT도 반복됩니다.

기본 PostgreSQL 스키마는 `MEASURE`, 기본 테이블명은 `water_level_log`,
기본 컬럼은 `created_at`, `level_value`입니다. 테이블이 없으면 프로그램이
자동 생성합니다.

다른 PC에서 접속하려면 `127.0.0.1` 대신 송출 PC의 내부 IP 주소를 사용하고,
Windows 방화벽에서 TCP 8554 포트를 허용해야 합니다.

## 저장소에 실행 파일이 없는 이유

FFmpeg 실행 파일은 GitHub 일반 저장소의 파일 크기 제한을 초과할 수 있습니다.
또한 FFmpeg와 MediaMTX는 각각의 라이선스를 따르므로 이 저장소에는 프로젝트
소스와 빌드 스크립트만 포함합니다.

## 사용 구성 요소

- [FFmpeg](https://ffmpeg.org/)
- [MediaMTX](https://github.com/bluenviron/mediamtx)
- [PyInstaller](https://pyinstaller.org/)
