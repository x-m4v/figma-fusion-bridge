"""Assemble release ZIPs without caches, credentials or local design documents."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=['macos', 'windows'])
    platform = parser.parse_args().platform
    version = __import__('json').loads((ROOT / 'package.json').read_text())['version']
    name = f'figma-fusion-bridge-{version}-{platform}-' + ('arm64' if platform == 'macos' else 'x64')
    stage = ROOT / 'dist' / 'release-stage' / name
    if stage.exists(): shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for filename in ['README.md', 'README.ru.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT / filename, stage / filename)
    shutil.copytree(ROOT / 'licenses', stage / 'licenses')
    plugin = stage / 'figma-plugin'
    plugin.mkdir()
    shutil.copy2(ROOT / 'packages/figma-plugin/manifest.json', plugin / 'manifest.json')
    shutil.copytree(ROOT / 'packages/figma-plugin/dist', plugin / 'dist')
    if platform == 'macos':
        shutil.copytree(ROOT / 'dist/Figma Fusion Bridge.app', stage / 'Figma Fusion Bridge.app')
        shutil.copytree(ROOT / 'resolve', stage / 'resolve', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'tests'))
        shutil.copytree(ROOT / 'bridge-python', stage / 'bridge-python', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'tests'))
        installer = stage / 'Install.command'
        installer.write_text('#!/bin/bash\nset -euo pipefail\ncd "$(dirname "$0")"\npython3 -c "import sys; assert sys.version_info >= (3,9), \'Python 3.9+ is required\'"\npython3 bridge-python/app.py --install\nopen "Figma Fusion Bridge.app"\n', encoding='utf-8')
        installer.chmod(0o755)
    else:
        shutil.copytree(ROOT / 'dist/windows/FigmaFusionBridge', stage / 'FigmaFusionBridge')
        (stage / 'Install.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\n"FigmaFusionBridge\FigmaFusionBridge.exe" --install\r\nif errorlevel 1 (pause & exit /b 1)\r\nstart "" "FigmaFusionBridge\FigmaFusionBridge.exe"\r\n', encoding='utf-8')
    output = ROOT / 'dist' / name
    if platform == 'macos':
        archive = str(output) + '.zip'
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), archive], check=True)
    else:
        archive = shutil.make_archive(str(output), 'zip', stage.parent, stage.name)
    archive = Path(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n')
    print(archive)

if __name__ == '__main__':
    main()
