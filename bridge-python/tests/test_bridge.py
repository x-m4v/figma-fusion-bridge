import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import pytest
from ffbridge_app.server import Bridge, State, MAX_BODY
from ffbridge.client import BridgeClient, Session
from ffbridge import paths


@pytest.fixture
def bridge(tmp_path):
    service = Bridge(tmp_path)
    service.start([0])
    yield service
    service.stop()
    assert not (tmp_path / 'session.json').exists()


def request(bridge, method, path, value=None, token=None, host=None):
    body = value if isinstance(value, bytes) else json.dumps(value).encode() if value is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{bridge.state.port}' + path, data=body, method=method)
    if token:
        req.add_header('X-FFBridge-Token', token)
    if host:
        req.add_header('Host', host)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read()
        try:
            data = json.loads(data)
        except (ValueError, UnicodeError):
            pass
        return response.code, data, response.headers


def test_discovery_pairing_and_authentication(bridge):
    assert request(bridge, 'GET', '/api/hello')[1]['app'] == 'figma-fusion-bridge'
    assert request(bridge, 'GET', '/api/status')[0] == 401
    assert request(bridge, 'POST', '/api/pair', {'code': 'WRONG'})[0] == 403
    status, body, headers = request(bridge, 'POST', '/api/pair', {'code': bridge.state.code.lower()})
    assert status == 200 and body['token'] == bridge.state.token
    assert request(bridge, 'GET', '/api/status', token=body['token'])[1]['paired']
    assert headers['Access-Control-Allow-Origin'] == '*'
    assert request(bridge, 'OPTIONS', '/api/transfer')[0] == 204
    assert request(bridge, 'GET', '/api/hello', host='evil.example')[0] == 403


def test_pairing_expiry_and_rate_limit(tmp_path):
    state = State(tmp_path)
    state.expires = 0
    assert state.pair(state.code)[0] == 403
    state.new_code()
    for _ in range(9):
        assert state.pair('wrong')[0] == 403
    assert state.pair(state.code)[0] == 429


def test_token_survives_restart(bridge):
    assert bridge.state.pair(bridge.state.code)[0] == 200
    restored = State(bridge.state.root)
    assert restored.token == bridge.state.token and restored.paired


def test_transfer_asset_and_report_roundtrip(bridge):
    token = bridge.state.token
    doc = {'schemaVersion': '1.0.0', 'transferId': '../../unsafe', 'nodes': [], 'assets': []}
    assert request(bridge, 'POST', '/api/transfer', doc, token)[0] == 200
    client = BridgeClient(Session(bridge.state.port, token))
    assert client.latest_transfer() == doc
    data = b'example image bytes'
    digest = hashlib.sha256(data).hexdigest()
    assert request(bridge, 'PUT', '/api/asset/' + digest, data, token)[0] == 201
    assert client.fetch_asset(digest) == data
    assert request(bridge, 'POST', '/api/asset/known', {'ids': [digest]}, token)[1]['known'] == [digest]
    assert request(bridge, 'PUT', '/api/asset/' + digest, b'wrong', token)[0] == 400
    client.report(doc['transferId'], {'status': 'prepared'})
    assert (bridge.state.root / 'history.json').exists()
    assert (bridge.state.root / 'Transfers/latest.json').exists()


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/transfer', b'{'),
    ('POST', '/api/transfer', {'schemaVersion': '2.0', 'transferId': 'id', 'nodes': []}),
    ('POST', '/api/pair', []),
    ('GET', '/api/asset/../../credentials.json', None),
    ('POST', '/api/asset/known', {'ids': ['../credentials.json']}),
    ('GET', '/api/transfer/wait?timeout=nan', None),
    ('GET', '/api/transfer/wait?timeout=-1', None),
])
def test_bad_requests_are_rejected(bridge, method, path, body):
    assert request(bridge, method, path, body, bridge.state.token)[0] == 400


def test_long_poll_wakes_on_transfer(bridge):
    client = BridgeClient(Session(bridge.state.port, bridge.state.token))
    result = []
    thread = threading.Thread(target=lambda: result.append(client.wait_for_transfer(2)))
    thread.start()
    doc = {'schemaVersion': '1.0', 'transferId': 'new', 'nodes': []}
    request(bridge, 'POST', '/api/transfer', doc, bridge.state.token)
    thread.join(4)
    assert result == [doc]


def test_empty_queue(bridge):
    client = BridgeClient(Session(bridge.state.port, bridge.state.token))
    assert client.latest_transfer() is None
    assert client.wait_for_transfer(0) is None


def test_duplicate_instance_does_not_replace_session(bridge):
    session = (bridge.state.root / 'session.json').read_bytes()
    other = Bridge(bridge.state.root)
    with pytest.raises(OSError, match='already running'):
        other.start([0])
    other.stop()
    assert (bridge.state.root / 'session.json').read_bytes() == session


def test_install_isolated_and_repair(tmp_path, monkeypatch):
    monkeypatch.setenv('FFBRIDGE_SUPPORT_DIR', str(tmp_path / 'данные с пробелами'))
    monkeypatch.setenv('FFBRIDGE_SCRIPTS_DIR', str(tmp_path / 'scripts'))
    from ffbridge_app.installer import install
    for _ in range(2):
        scripts = install()
        assert (scripts / 'Comp/Figma Fusion Bridge - Receive.lua').is_file()
        assert (Path(paths.support_dir()) / 'lib/ffbridge.lua').is_file()
        assert (Path(paths.support_dir()) / 'lib/ffbridge_launcher.py').is_file()
    helper = Path(paths.support_dir()) / 'lib/ffbridge_launcher.py'
    result = subprocess.run([sys.executable, str(helper), '--help'], capture_output=True)
    assert result.returncode == 0


def test_windows_paths(monkeypatch):
    monkeypatch.delenv('FFBRIDGE_SUPPORT_DIR', raising=False)
    monkeypatch.delenv('FFBRIDGE_SCRIPTS_DIR', raising=False)
    monkeypatch.setattr(paths.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', '/local')
    monkeypatch.setenv('APPDATA', '/roaming')
    assert paths.support_dir() == os.path.join('/local', 'FigmaFusionBridge')
    assert paths.resolve_scripts_dir() == os.path.join('/roaming', 'Blackmagic Design', 'DaVinci Resolve', 'Support', 'Fusion', 'Scripts')


def test_cli_builds_sample_via_actual_http(bridge, tmp_path):
    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / 'examples/starter-transfer.json').read_text())
    assert request(bridge, 'POST', '/api/transfer', doc, bridge.state.token)[0] == 200
    environment = dict(os.environ, FFBRIDGE_SUPPORT_DIR=str(bridge.state.root), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, str(root / 'bridge-python/app.py'), '--cli', 'build',
                             '--width', '1920', '--height', '1080', '--fusion-color-space', 'UNMANAGED'],
                            env=environment, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    marker = [line for line in result.stdout.splitlines() if line.startswith('FFBRIDGE_RESULT ')][-1]
    payload = json.loads(marker.removeprefix('FFBRIDGE_RESULT '))
    assert payload['status'] == 'ok' and Path(payload['setting']).is_file()
    assert 'Tools = ordered()' in Path(payload['setting']).read_text(encoding='utf-8')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows GDI')
def test_windows_real_fonts():
    from ffbridge.winfonts import enumerate_fonts
    catalogue = enumerate_fonts()
    assert len(catalogue) > 10
    assert all(k == k.lower() and v for k, v in catalogue.items())
