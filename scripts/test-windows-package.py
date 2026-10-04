"""Exercise the packaged runtime through the real Lua launcher and cmd.exe."""
import os
from pathlib import Path
import subprocess
from lupa.lua51 import LuaRuntime

root = Path(__file__).resolve().parents[1]
exe = root / 'dist/windows/FigmaFusionBridge/FigmaFusionBridge.exe'
subprocess.run([str(exe), '--install'], check=True)
lua = LuaRuntime(unpack_returned_tuples=True)
helper = lua.execute((root / 'resolve/lua/ffbridge.lua').read_text(encoding='utf-8'))
assert helper.IS_WINDOWS
output = helper.run_cli('test')
assert isinstance(output, str) and 'FFBRIDGE_RESULT ' in output, output
assert helper.result_field(output, 'status') in ('ok', 'error')
assert 'Python' in output
print('Real Lua → cmd.exe → packaged CLI passed with Unicode/spaces in support path.')
