"""Install only this project's payload into per-user directories."""
from pathlib import Path
import shutil
import sys
from ffbridge.paths import support_dir, resolve_scripts_dir


def payload_root():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'payload'
    return Path(__file__).resolve().parents[2] / 'resolve'


def install():
    payload = payload_root()
    library = Path(support_dir()) / 'lib'
    scripts = Path(resolve_scripts_dir())
    library.mkdir(parents=True, exist_ok=True)
    # Merge preserves user data outside the installed code directory.
    shutil.copytree(payload / 'ffbridge', library / 'ffbridge', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(payload / 'lua' / 'ffbridge.lua', library / 'ffbridge.lua')
    shutil.copy2(payload / 'ffbridge_launcher.py', library / 'ffbridge_launcher.py')
    for source in (payload / 'scripts').rglob('*.lua'):
        target = scripts / source.relative_to(payload / 'scripts')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (library / 'python-path.txt').write_text(sys.executable + '\n', encoding='utf-8')
    return scripts
