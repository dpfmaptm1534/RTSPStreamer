# Windows 배포판 만들기

프로젝트 루트에 아래 파일을 준비합니다.

- `ffmpeg.exe`
- `mediamtx.exe`
- `mediamtx.yml`

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
.\build.ps1
```

완성된 배포판은 `dist\RTSPStreamer` 폴더에 생성됩니다. 사용자에게는
`RTSPStreamer.exe`만 따로 보내지 말고 이 폴더 전체를 ZIP으로 압축해서
전달해야 합니다.

## 단일 파일 방식을 기본으로 사용하지 않는 이유

FFmpeg와 MediaMTX의 크기가 약 250MB이므로 하나의 EXE 안에 넣으면 실행할
때마다 임시 폴더로 압축 해제될 수 있습니다. 시작이 느려지고 백신 오탐이나
임시 폴더 권한 문제도 증가하므로 이 프로젝트는 `--onedir` 방식을 사용합니다.
