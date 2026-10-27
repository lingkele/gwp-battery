# Build GProBattery.exe (single file, windowed).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install --quiet hidapi pillow pystray pyinstaller

New-Item -ItemType Directory -Force assets | Out-Null
& $py tools\make_icon.py

# PyInstaller logs to stderr; keep that from tripping $ErrorActionPreference.
$ErrorActionPreference = "Continue"
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name GProBattery --icon assets\app.ico app.py 2>&1 | ForEach-Object { Write-Host $_ }
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($code -ne 0) { throw "PyInstaller failed with exit code $code" }
Write-Host ""
Write-Host "done -> dist\GProBattery.exe" -ForegroundColor Green
