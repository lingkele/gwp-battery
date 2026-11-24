# Build the app, its uninstaller and the setup exe.
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

function Invoke-PyInstaller {
    param([string[]] $Arguments, [string] $What)
    # PyInstaller logs to stderr; keep that from tripping $ErrorActionPreference.
    $script:ErrorActionPreference = "Continue"
    & $py -m PyInstaller @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    $script:ErrorActionPreference = "Stop"
    if ($code -ne 0) { throw "PyInstaller failed for $What (exit $code)" }
}

Invoke-PyInstaller -What "app" -Arguments @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "GProBattery", "--icon", "assets\app.ico", "app.py")

Invoke-PyInstaller -What "uninstaller" -Arguments @(
    "--noconfirm", "--onefile", "--windowed",
    "--name", "GProBatteryUninstall", "--icon", "assets\app.ico", "uninstaller.py")

Invoke-PyInstaller -What "setup" -Arguments @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "GProBattery-Setup", "--icon", "assets\app.ico",
    "--add-data", "dist\GProBattery.exe;payload",
    "--add-data", "dist\GProBatteryUninstall.exe;payload",
    "installer.py")

Write-Host ""
Write-Host "done ->" -ForegroundColor Green
Write-Host "  dist\GProBattery.exe            (便携版)"
Write-Host "  dist\GProBatteryUninstall.exe   (卸载程序)"
Write-Host "  dist\GProBattery-Setup.exe      (安装包)"
