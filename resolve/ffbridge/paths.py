"""Where the bridge keeps its files on macOS.

Assets live under Application Support, not in a temporary directory. That is a
deliberate choice: a Fusion Loader holds a *path*, so putting transferred images
in ``/tmp`` means every import silently breaks the next time the machine reboots
and the folder is swept. Application Support is the correct location for data
the user's documents depend on.
"""

from __future__ import annotations

import os
import sys

APP_NAME = "FigmaFusionBridge"


def support_dir() -> str:
    override = os.environ.get("FFBRIDGE_SUPPORT_DIR")
    if override:
        return os.path.abspath(override)
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")), APP_NAME)
    return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")


def assets_dir() -> str:
    return os.path.join(support_dir(), "Assets")


def transfers_dir() -> str:
    return os.path.join(support_dir(), "Transfers")


def manifests_dir() -> str:
    return os.path.join(support_dir(), "Manifests")


def logs_dir() -> str:
    if os.environ.get("FFBRIDGE_SUPPORT_DIR") or sys.platform == "win32":
        return os.path.join(support_dir(), "Logs")
    return os.path.expanduser(f"~/Library/Logs/{APP_NAME}")


def session_file() -> str:
    return os.path.join(support_dir(), "session.json")


def resolve_scripts_dir() -> str:
    """The per-user script folder Resolve scans at startup.

    Taken verbatim from the Scripting SDK README shipped with Resolve; the
    all-users location under /Library is deliberately not used because writing
    there needs an administrator and gains nothing.
    """
    override = os.environ.get("FFBRIDGE_SCRIPTS_DIR")
    if override:
        return os.path.abspath(override)
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~/AppData/Roaming")),
                            "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion", "Scripts")
    return os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"
    )


def ensure_dirs() -> None:
    for d in (support_dir(), assets_dir(), transfers_dir(), manifests_dir(), logs_dir()):
        os.makedirs(d, exist_ok=True)
