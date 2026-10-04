"""Install only this project's payload into per-user directories."""
from pathlib import Path
import shutil
import sys
import json
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
    helper = (payload / 'lua' / 'ffbridge.lua').read_text(encoding='utf-8')
    if sys.platform == 'win32':
        # Lua's narrow CRT cannot reliably open Unicode paths on Windows.
        # Embed paths and the helper into the menu commands, then use wide Win32 APIs.
        config = 'local M = {LIB_DIR = ' + json.dumps(str(library).replace('\\', '/'), ensure_ascii=False) + ', RUNTIME = ' + json.dumps(sys.executable.replace('\\', '/'), ensure_ascii=False) + '} '
        helper = helper.replace('local M = {}', config, 1)
        windows = (payload / 'lua' / 'windows_process.lua').read_text(encoding='utf-8')
        helper = helper.rsplit('return M', 1)[0] + windows + '\nreturn M\n'
    (library / 'ffbridge.lua').write_text(helper, encoding='utf-8')
    shutil.copy2(payload / 'ffbridge_launcher.py', library / 'ffbridge_launcher.py')
    for source in (payload / 'scripts').rglob('*.lua'):
        target = scripts / source.relative_to(payload / 'scripts')
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = source.read_text(encoding='utf-8')
        if sys.platform == 'win32':
            start = contents.index('local base = os.getenv("FFBRIDGE_SUPPORT_DIR")')
            marker = 'local ok, ffb = pcall(dofile, base .. "/lib/ffbridge.lua")'
            end = contents.index(marker, start) + len(marker)
            contents = contents[:start] + 'local ok, ffb = pcall(function()\n' + helper + '\nend)' + contents[end:]
        target.write_text(contents, encoding='utf-8')
    (library / 'python-path.txt').write_text(sys.executable + '\n', encoding='utf-8')
    return scripts
