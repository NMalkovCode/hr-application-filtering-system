# Build dist\HRScreening.exe and run its self-test.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "Running tests..."
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

if (-not (Test-Path "packaging\app.ico")) { & $python packaging\make_icon.py }

Write-Host "Building HRScreening.exe..."
& $python -m PyInstaller --clean --noconfirm --distpath dist --workpath build\pyinstaller packaging\HRScreening.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "Self-testing the exe..."
$report = Join-Path $env:TEMP "HRScreening_selftest.txt"
$proc = Start-Process -FilePath "dist\HRScreening.exe" -ArgumentList "--self-test", "`"$report`"" -Wait -PassThru
Get-Content $report
if ($proc.ExitCode -ne 0) { throw "Self-test of the exe failed." }

Write-Host "Writing the user guide..."
& $python packaging\make_user_guide.py
if (Test-Path "docs\HR_User_Guide.pdf") { Copy-Item "docs\HR_User_Guide.pdf" "dist\" -Force }
else { Copy-Item "docs\HR_User_Guide.docx" "dist\" -Force }

$size = (Get-Item "dist\HRScreening.exe").Length / 1MB
Write-Host ("Built dist\HRScreening.exe ({0:N0} MB)" -f $size)

# Installer (optional): needs Inno Setup 6 - https://jrsoftware.org/isinfo.php
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    $version = (& $python -c "import hr_screening; print(hr_screening.__version__)").Trim()
    Write-Host "Building the installer (version $version)..."
    & $iscc /Q "/DAppVersion=$version" packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
    Write-Host "Built dist\HRScreening-Setup-$version.exe"
} else {
    Write-Host "Inno Setup 6 not found - skipping the installer (the exe above works without one)."
}
