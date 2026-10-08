$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$DistDir = Join-Path $ProjectDir "dist"
$PackageDir = Join-Path $DistDir "RTSPStreamer"

Set-Location $ProjectDir

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python was not found: $Python"
}

foreach ($requiredFile in @("main.py", "ffmpeg.exe", "mediamtx.exe", "mediamtx.yml")) {
    if (-not (Test-Path (Join-Path $ProjectDir $requiredFile))) {
        throw "Required file was not found: $requiredFile"
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --collect-all "tkinterdnd2" `
    --name "RTSPStreamer" `
    --distpath $DistDir `
    --workpath (Join-Path $ProjectDir "build") `
    --specpath $ProjectDir `
    (Join-Path $ProjectDir "main.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Copy-Item (Join-Path $ProjectDir "ffmpeg.exe") $PackageDir -Force
Copy-Item (Join-Path $ProjectDir "mediamtx.exe") $PackageDir -Force
Copy-Item (Join-Path $ProjectDir "mediamtx.yml") $PackageDir -Force

$Readme = @"
RTSP Streamer

Run:
  Double-click RTSPStreamer.exe.

Default publish/playback URL:
  rtsp://127.0.0.1:8554/live/stream

Input:
  Select either a video file or a webcam from the top source selector.

Important:
  Keep ffmpeg.exe, mediamtx.exe, mediamtx.yml, and the _internal
  directory beside RTSPStreamer.exe.
  Distribute the entire RTSPStreamer directory as a ZIP archive.
"@

Set-Content -LiteralPath (Join-Path $PackageDir "README.txt") -Value $Readme -Encoding UTF8

Write-Host ""
Write-Host "Build completed:"
Write-Host (Join-Path $PackageDir "RTSPStreamer.exe")
Write-Host ""
Write-Host "Distribute the entire dist\RTSPStreamer directory."
