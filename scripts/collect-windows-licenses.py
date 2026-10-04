"""Capture licenses from the actual Windows build environment, not guessed text."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1] / 'licenses'
root.mkdir(exist_ok=True)
python_root = Path(sys.base_prefix)
python_license = python_root / 'LICENSE.txt'
if not python_license.is_file():
    raise SystemExit('Python LICENSE.txt is required for redistribution.')
shutil.copy2(python_license, root / 'Python-LICENSE.txt')
for library in ['tcl8.6', 'tk8.6']:
    matches = list((python_root / 'tcl' / library).glob('*license*')) + list((python_root / 'tcl' / library).glob('*License*'))
    if not matches:
        raise SystemExit(f'Missing {library} license in Python installation.')
    for path in matches:
        shutil.copy2(path, root / (library + '-' + path.name))
for package in ['pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'packaging', 'pefile', 'pywin32-ctypes']:
    dist = metadata.distribution(package)
    found = False
    for item in dist.files or []:
        if 'license' in item.name.lower() or 'copying' in item.name.lower():
            source = dist.locate_file(item)
            if source.is_file():
                shutil.copy2(source, root / (package + '-' + item.name))
                found = True
    if not found:
        raise SystemExit(f'Missing license text for {package}.')
