"""Exercise the packaged runtime through the real Lua launcher and cmd.exe."""
import os
from pathlib import Path
import subprocess
import shutil
from lupa.luajit21 import LuaRuntime

root = Path(__file__).resolve().parents[1]
original = root / 'dist/windows/FigmaFusionBridge'
installed = Path(os.environ['RUNNER_TEMP']) / 'Bridge программа с пробелами'
shutil.copytree(original, installed, dirs_exist_ok=True)
exe = installed / 'FigmaFusionBridge.exe'
subprocess.run([str(exe), '--install'], check=True)
lua = LuaRuntime(unpack_returned_tuples=True)
helper = lua.execute((Path(os.environ['FFBRIDGE_SUPPORT_DIR']) / 'lib/ffbridge.lua').read_text(encoding='utf-8'))
assert helper.IS_WINDOWS
output = helper.run_cli('test')
assert isinstance(output, str) and 'FFBRIDGE_RESULT ' in output, output
assert helper.result_field(output, 'status') in ('ok', 'error')
assert 'Python' in output
print('Real LuaJIT -> Unicode Win32 process -> packaged CLI passed with Unicode/spaces in support path.')
