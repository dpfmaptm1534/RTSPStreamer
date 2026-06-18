# RTSPStreamer

영상 파일을 선택하면 FFmpeg와 MediaMTX를 이용해 Windows에서 RTSP 스트림으로
반복 송출하는 간단한 GUI 프로그램입니다.

기본 송출 및 재생 주소:

```text
rtsp://127.0.0.1:8554/live/stream
```

## 주요 기능

- MP4, AVI, MKV, MOV, WMV, WebM, TS 영상 지원
- 영상 무한 반복 송출
- H.264 영상 및 AAC 오디오 송출
- 내장 MediaMTX RTSP 서버 자동 실행
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
2. 송출할 영상 파일을 선택합니다.
3. RTSP 주소를 확인하고 **송출 시작**을 누릅니다.
4. VLC 등의 플레이어에서 같은 RTSP 주소를 엽니다.

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
