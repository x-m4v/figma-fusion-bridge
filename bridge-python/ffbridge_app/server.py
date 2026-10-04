"""Loopback bridge compatible with the Figma and Resolve clients."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from ffbridge.paths import support_dir

PORTS = range(8787, 8792)
MAX_BODY = 64 * 1024 * 1024
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.part')
    try:
        with open(temporary, 'xb') as stream:
            if os.name != 'nt':
                os.chmod(temporary, 0o600)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class State:
    def __init__(self, root=None):
        self.root = Path(root or support_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Condition()
        self.port = 0
        self.latest = None
        self.last_transfer = ''
        self.figma_seen = 0
        self.resolve_seen = 0
        self.reports = []
        self.attempts = []
        self.token = secrets.token_hex(32)
        self.paired = False
        credentials = self.root / 'credentials.json'
        if credentials.exists():
            value = json.loads(credentials.read_text(encoding='utf-8'))
            if not DIGEST.fullmatch(str(value.get('token', ''))):
                raise ValueError('Invalid credentials file. Remove it to pair again.')
            self.token, self.paired = value['token'], bool(value.get('paired'))
        self.save_credentials()
        self.new_code()

    def save_credentials(self):
        atomic_write(self.root / 'credentials.json', json.dumps({'token': self.token, 'paired': self.paired}).encode())

    def new_code(self):
        with self.lock:
            self.code = ''.join(secrets.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(6))
            self.expires = time.monotonic() + 600
            return self.code

    def pair(self, code):
        with self.lock:
            now = time.monotonic()
            self.attempts = [t for t in self.attempts if now - t < 60]
            if len(self.attempts) >= 10:
                return 429, {'error': 'Too many attempts. Wait one minute.'}
            self.attempts.append(now)
            if now > self.expires or not hmac.compare_digest(str(code).strip().upper(), self.code):
                return 403, {'error': 'Invalid or expired pairing code.'}
            self.paired = True
            self.figma_seen = now
            self.save_credentials()
            return 200, {'token': self.token}

    def route(self, method, target, headers, body):
        parsed = urlsplit(target)
        path = parsed.path
        if method == 'OPTIONS':
            return 204, b'', 'text/plain'
        if (method, path) == ('GET', '/api/hello'):
            return 200, {'app': 'figma-fusion-bridge', 'version': '0.1.0', 'schemaVersion': '1.0.0', 'paired': self.paired}, None
        if (method, path) == ('POST', '/api/pair'):
            status, value = self.pair(json.loads(body).get('code', ''))
            return status, value, None
        if not hmac.compare_digest(headers.get('X-FFBridge-Token', ''), self.token):
            return 401, {'error': 'Client is not paired.'}, None
        with self.lock:
            now = time.monotonic()
            if headers.get('X-FFBridge-Client') == 'figma':
                self.figma_seen = now
            if headers.get('X-FFBridge-Client') == 'resolve':
                self.resolve_seen = now
            if (method, path) == ('GET', '/api/status'):
                return 200, {'version': '0.1.0', 'paired': self.paired,
                             'figmaConnected': now - self.figma_seen < 60,
                             'resolveConnected': now - self.resolve_seen < 60,
                             'fusionReady': False, 'lastTransferAt': self.last_transfer}, None
            if (method, path) == ('POST', '/api/transfer'):
                value = json.loads(body)
                if (not isinstance(value, dict) or not isinstance(value.get('transferId'), str)
                    or not value['transferId'] or str(value.get('schemaVersion', '')).split('.')[0] != '1'
                    or not isinstance(value.get('nodes'), list) or not isinstance(value.get('assets', []), list)):
                    return 400, {'error': 'Invalid transfer or incompatible schema.'}, None
                atomic_write(self.root / 'Transfers' / 'latest.json', body)
                self.latest = body
                self.last_transfer = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                self.lock.notify_all()
                return 200, {'ok': True, 'transferId': value['transferId']}, None
            if method == 'GET' and path in ('/api/transfer/latest', '/api/transfer/wait'):
                if path.endswith('/wait') and self.latest is None:
                    seconds = float(parse_qs(parsed.query).get('timeout', ['30'])[0])
                    if not 0 <= seconds <= 120:
                        return 400, {'error': 'Timeout must be between 0 and 120.'}, None
                    self.lock.wait_for(lambda: self.latest is not None, timeout=seconds)
                if self.latest is None:
                    return 404, {'error': 'There is nothing waiting to be received.'}, None
                return 200, self.latest, 'application/json'
            if (method, path) == ('POST', '/api/transfer/report'):
                value = json.loads(body)
                if not isinstance(value, dict) or not isinstance(value.get('transferId'), str):
                    return 400, {'error': 'Expected transfer id.'}, None
                self.reports = (self.reports + [value])[-100:]
                atomic_write(self.root / 'history.json', json.dumps(self.reports).encode())
                return 200, {'ok': True}, None
            if (method, path) == ('POST', '/api/figma/pull'):
                return 404, {'error': 'Pull is not implemented. Use Send to Fusion in Figma.'}, None
            if (method, path) == ('POST', '/api/asset/known'):
                ids = json.loads(body).get('ids')
                if not isinstance(ids, list) or not all(isinstance(i, str) and DIGEST.fullmatch(i) for i in ids):
                    return 400, {'error': 'Expected SHA-256 asset ids.'}, None
                return 200, {'known': [i for i in ids if (self.root / 'BridgeAssets' / i).is_file()]}, None
            if path.startswith('/api/asset/'):
                digest = path.removeprefix('/api/asset/')
                if not DIGEST.fullmatch(digest):
                    return 400, {'error': 'Invalid asset id.'}, None
                location = self.root / 'BridgeAssets' / digest
                if method == 'PUT':
                    if hashlib.sha256(body).hexdigest() != digest:
                        return 400, {'error': 'Asset checksum does not match.'}, None
                    atomic_write(location, body)
                    return 201, b'', 'text/plain'
                if method == 'GET':
                    if location.is_file():
                        return 200, location.read_bytes(), 'application/octet-stream'
        return 404, {'error': 'Unknown endpoint.'}, None


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 closes sockets after each request, avoiding unbounded idle keep-alive.
    server_version = 'FFBridge/0.1'

    def log_message(self, *args):
        pass  # Never log credentials or design data.

    def handle_request(self):
        try:
            host = urlsplit('//'+self.headers.get('Host', '')).hostname
            if host not in ('localhost', '127.0.0.1', '::1'):
                self.reply(403, {'error': 'Invalid host.'})
                return
            raw_lengths = self.headers.get_all('Content-Length', [])
            length = int(raw_lengths[0]) if len(raw_lengths) == 1 else 0
            if len(raw_lengths) > 1 or length < 0 or self.headers.get('Transfer-Encoding'):
                self.reply(400, {'error': 'Invalid request framing.'})
                return
            if length > MAX_BODY:
                self.reply(413, {'error': 'Request exceeds 64 MB.'})
                return
            self.connection.settimeout(15)
            body = self.rfile.read(length)
            if len(body) != length:
                self.reply(400, {'error': 'Truncated request.'})
                return
            status, payload, mime = self.server.state.route(self.command, self.path, self.headers, body)
            self.reply(status, payload, mime)
        except (ValueError, TypeError, AttributeError, UnicodeError):
            self.reply(400, {'error': 'Invalid request.'})
        except OSError:
            self.reply(500, {'error': 'Unable to read or write bridge data.'})

    def reply(self, status, payload, mime=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime or 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-FFBridge-Token, X-FFBridge-Client, X-FFBridge-Filename')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        if data:
            self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_OPTIONS = handle_request


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class ServerV6(Server):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


class Bridge:
    def __init__(self, root=None):
        self.state = State(root)
        self.servers = []
        self.threads = []
        self.lease = None

    def start(self, ports=PORTS):
        self.lease = open(self.state.root / 'bridge.lock', 'a+b')
        self.lease.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                if self.lease.read(1) == b'':
                    self.lease.write(b'0'); self.lease.flush()
                self.lease.seek(0)
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close(); self.lease = None
            raise OSError('The bridge is already running for this user.')
        for port in ports:
            try:
                server = Server(('127.0.0.1', port), Handler)
            except OSError:
                continue
            self.servers.append(server)
            self.state.port = server.server_address[1]
            try:
                self.servers.append(ServerV6(('::1', self.state.port), Handler))
            except OSError:
                pass
            break
        if not self.servers:
            self.lease.close(); self.lease = None
            raise OSError('Ports 8787–8791 are unavailable.')
        atomic_write(self.state.root / 'session.json', json.dumps({'port': self.state.port, 'token': self.state.token, 'pid': os.getpid()}).encode())
        for server in self.servers:
            server.state = self.state
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start(); self.threads.append(thread)
        return self.state.port

    def stop(self):
        for server in self.servers:
            server.shutdown(); server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.servers.clear(); self.threads.clear()
        if self.lease is not None:
            (self.state.root / 'session.json').unlink(missing_ok=True)
            self.lease.close(); self.lease = None
