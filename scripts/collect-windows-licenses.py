"""Capture licenses from the actual Windows build environment, not guessed text."""
from importlib import metadata
from pathlib import Path
import shutil
import sys
import re
import tkinter
import urllib.request

root = Path(__file__).resolve().parents[1] / 'licenses'
root.mkdir(exist_ok=True)
python_root = Path(sys.base_prefix)
python_license = python_root / 'LICENSE.txt'
if not python_license.is_file():
    raise SystemExit('Python LICENSE.txt is required for redistribution.')
shutil.copy2(python_license, root / 'Python-LICENSE.txt')
runtime = tkinter.Tk()
runtime.withdraw()
versions = {'tcl': runtime.tk.call('info', 'patchlevel'), 'tk': runtime.tk.call('package', 'provide', 'Tk')}
runtime.destroy()
for library, version in versions.items():
    if not re.fullmatch(r'8\.6\.[0-9]+', version):
        raise SystemExit(f'Unexpected {library} version: {version}')
    local = python_root / 'tcl' / (library + '8.6') / 'license.terms'
    destination = root / (library + '-' + version + '-license.terms')
    if local.is_file():
        shutil.copy2(local, destination)
    else:
        # CPython Windows installers may omit the separate Tcl/Tk license files.
        # Retrieve the exact runtime version's notice from the official tagged source.
        tag = 'core-' + version.replace('.', '-')
        url = f'https://raw.githubusercontent.com/tcltk/{library}/{tag}/license.terms'
        with urllib.request.urlopen(url, timeout=30) as response:
            notice = response.read()
        if b'copyright' not in notice.lower() or b'permission' not in notice.lower():
            raise SystemExit(f'Invalid {library} notice at {url}')
        destination.write_bytes(notice)
        (root / (library + '-NOTICE-SOURCE.txt')).write_text(url + '\n', encoding='utf-8')
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
