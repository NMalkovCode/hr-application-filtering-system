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
