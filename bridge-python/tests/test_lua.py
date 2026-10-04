"""Execute actual Resolve helpers in Lua 5.1 with mocked native composition APIs."""
from pathlib import Path
import json
import pytest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'resolve/lua/ffbridge.lua'


def helper(windows=False):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      os.getenv = function(key)
        if key == 'FFBRIDGE_SUPPORT_DIR' then return 'C:/Users/Дизайнер/Bridge data' end
      end
      io.open = function() return nil end
    ''')
    if windows:
        lua.execute('package.config = "\\\\\\n;\\n?\\n!\\n-\\n"')
    else:
        lua.execute('package.config = "/\\n;\\n?\\n!\\n-\\n"')
    return lua, lua.execute(HELPER.read_text(encoding='utf-8'))


@pytest.mark.parametrize('path', ['C:\\Users\\Дизайнер\\AppData\\Local\\Bridge data\\transfer.setting', '/Users/Designer/Bridge data/file.setting'])
def test_result_decodes_real_json_paths(path):
    lua, module = helper(True)
    line = 'FFBRIDGE_RESULT ' + json.dumps({'setting': path, 'nodes': 42}, ensure_ascii=False)
    assert module.result_field(line, 'setting') == path
    assert module.result_field(line, 'nodes') == '42'


def test_shell_quoting():
    _, posix = helper(False)
    assert posix.quote("/Users/O'Brien/$demo") == "'/Users/O'\\''Brien/$demo'"
    _, windows = helper(True)
    assert windows.quote('C:/Users/Дизайнер/Bridge data/FigmaFusionBridge.exe').startswith('"C:/')
    for character in ['%', '!', '"', '\n']:
        with pytest.raises(Exception, match='Unsupported shell characters'):
            windows.quote('C:/bad' + character + 'path')


@pytest.mark.parametrize('windows', [True, False])
def test_cli_command_for_installed_runtime(windows):
    lua, module = helper(windows)
    runtime = 'C:/Bridge data/FigmaFusionBridge.exe' if windows else '/usr/bin/python3'
    module.find_python = lambda: runtime
    lua.execute('''
        recorded = nil
        io.popen = function(cmd)
          recorded = cmd
          return { read = function() return 'FFBRIDGE_RESULT {"status":"ok"}' end,
                   close = function() return true end }
        end
    ''')
    assert 'FFBRIDGE_RESULT' in module.run_cli('test')
    command = lua.globals().recorded
    if windows:
        assert command == 'cmd /d /s /c ""C:/Bridge data/FigmaFusionBridge.exe" --cli test 2>&1"'
    else:
        assert 'ffbridge_launcher.py' in command and 'PYTHONPATH=' not in command


def test_lua_installer_scripts_compile():
    lua, _ = helper(True)
    compile_chunk = lua.eval('function(s) local f, e = loadstring(s); return f ~= nil, e end')
    for source in (ROOT / 'resolve/scripts').rglob('*.lua'):
        ok, error = compile_chunk(source.read_text())
        assert ok, error
