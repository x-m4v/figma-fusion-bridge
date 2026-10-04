# Source installation. Run from a normal PowerShell prompt; no administrator needed.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.11 (64-bit) from python.org, including the py launcher.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 24 LTS first.' }
& py -3.11 -c "import sys; assert sys.version_info >= (3,11)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required.' }
& npm.cmd ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Figma plugin build failed.' }
& py -3.11 bridge-python/app.py --install
if ($LASTEXITCODE -ne 0) { throw 'Resolve script installation failed.' }
Write-Host "Import $Root\packages\figma-plugin\manifest.json in Figma desktop."
& py -3.11 bridge-python/app.py
