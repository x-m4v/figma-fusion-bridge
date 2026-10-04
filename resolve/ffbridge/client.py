"""HTTP client for the local bridge.

Built on ``urllib`` from the standard library and nothing else. That is a hard
requirement rather than a preference: this code runs inside DaVinci Resolve's
embedded Python, where ``pip install`` is not something we can ask a designer to
do, and where assuming ``requests`` or ``websocket-client`` is present would
make the tool fail on a stock installation.

The same constraint rules out a WebSocket client on this side, so Resolve pulls
work with a long poll instead. A long poll on loopback delivers in roughly the
time it takes the bridge to write the response — fast enough that Live Sync
feels immediate — and it costs nothing while idle.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .paths import session_file

DEFAULT_PORT = 8787
#: Ports tried in order when the default is taken. Kept short and deterministic
#: so a user reading the log can tell which one is in use.
PORT_SCAN = (8787, 8788, 8789, 8790, 8791)


class BridgeError(Exception):
    """A failure that should be shown to the user in plain language."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class Session:
    port: int
    token: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def load_session(path: Optional[str] = None) -> Session:
    """Read the bridge's session file.

    The token in this file is what stops any local web page from driving
    Resolve: loopback ports are reachable from any page the user has open, so
    the port alone is not a permission.
    """
    p = path or session_file()
    if not os.path.exists(p):
        raise BridgeError(
            "The Figma Fusion Bridge app does not appear to be running. "
            "Start it, then try again.",
            detail=f"No session file at {p}",
        )
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return Session(int(data["port"]), str(data["token"]))
    except (ValueError, KeyError, OSError) as exc:
        raise BridgeError(
            "The bridge's session file is unreadable. Restart the Figma Fusion "
            "Bridge app to recreate it.",
            detail=f"{type(exc).__name__}: {exc}",
        )


class BridgeClient:
    def __init__(self, session: Optional[Session] = None, timeout: float = 10.0) -> None:
        self.session = session or load_session()
        self.timeout = timeout

    def _request(
        self, method: str, path: str, body: Optional[bytes] = None,
        content_type: str = "application/json", timeout: Optional[float] = None,
    ) -> bytes:
        url = self.session.base_url + path
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("X-FFBridge-Token", self.session.token)
        req.add_header("X-FFBridge-Client", "resolve")
        if body is not None:
            req.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if exc.code == 401:
                raise BridgeError(
                    "Resolve could not authenticate with the bridge. Restart the "
                    "Figma Fusion Bridge app and try again.",
                    detail=detail,
                )
            if exc.code == 404:
                raise BridgeError("There is nothing waiting to be received.", detail=detail)
            raise BridgeError(
                f"The bridge rejected the request (HTTP {exc.code}).", detail=detail
            )
        except urllib.error.URLError as exc:
            raise BridgeError(
                "Could not reach the Figma Fusion Bridge app on this computer. "
                "Check that it is running.",
                detail=f"{exc.reason}",
            )
        except socket.timeout:
            raise BridgeError("The bridge did not respond in time.", detail="socket timeout")

    # -- API ---------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return json.loads(self._request("GET", "/api/status") or b"{}")

    def latest_transfer(self) -> Optional[Dict[str, Any]]:
        """The most recent pending transfer, or None if there is none."""
        try:
            raw = self._request("GET", "/api/transfer/latest")
        except BridgeError as exc:
            if "nothing waiting" in exc.message:
                return None
            raise
        return json.loads(raw) if raw else None

    def wait_for_transfer(self, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Long-poll for the next transfer. Returns None on timeout."""
        try:
            raw = self._request(
                "GET", f"/api/transfer/wait?timeout={int(timeout)}",
                timeout=timeout + 5.0,
            )
        except BridgeError as exc:
            if "did not respond" in exc.message or "nothing waiting" in exc.message:
                return None
            raise
        return json.loads(raw) if raw else None

    def fetch_asset(self, asset_id: str) -> bytes:
        return self._request("GET", f"/api/asset/{asset_id}", timeout=120.0)

    def request_selection(self) -> Optional[Dict[str, Any]]:
        """Ask the plugin for the current selection, without leaving Resolve."""
        raw = self._request("POST", "/api/figma/pull", body=b"{}", timeout=30.0)
        return json.loads(raw) if raw else None

    def report(self, transfer_id: str, payload: Dict[str, Any]) -> None:
        """Send the import result back so the bridge and the plugin can show it."""
        body = json.dumps({"transferId": transfer_id, **payload}).encode("utf-8")
        try:
            self._request("POST", "/api/transfer/report", body=body)
        except BridgeError:
            # Reporting is best-effort. Failing to report must never turn a
            # successful import into a visible failure.
            pass
