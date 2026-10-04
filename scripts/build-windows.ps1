$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& python -m PyInstaller --noconfirm --clean --onedir --console --name FigmaFusionBridge `
  --distpath dist/windows --workpath dist/pyinstaller-build --specpath dist `
  --paths "$Root\resolve" --paths "$Root\bridge-python" --collect-submodules ffbridge `
  --add-data "$Root\resolve;payload" "$Root\bridge-python\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }
& dist/windows/FigmaFusionBridge/FigmaFusionBridge.exe --self-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged application self-test failed.' }
& python scripts/collect-windows-licenses.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime licenses missing.' }
& python scripts/package-release.py windows
if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
