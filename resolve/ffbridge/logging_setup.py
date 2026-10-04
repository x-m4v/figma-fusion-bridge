"""Structured logging.

Logs go to ``~/Library/Logs/FigmaFusionBridge`` — the standard macOS location,
so Console.app finds them and a diagnostic report is one zip of one folder.

Every record carries the transfer id where one is known, because the question
being answered when someone reads these files is almost always "what happened
during *that* transfer", and grepping by id is how they get there.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from .paths import logs_dir

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"


class _TransferFilter(logging.Filter):
    """Attaches the current transfer id to every record."""

    transfer_id: str = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        record.transferId = getattr(record, "transferId", self.transfer_id)
        return True


_filter = _TransferFilter()


def set_transfer_id(transfer_id: str) -> None:
    _filter.transfer_id = transfer_id or "-"


def configure(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("ffbridge")
    root.setLevel(level)
    root.addFilter(_filter)

    try:
        os.makedirs(logs_dir(), exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(logs_dir(), "resolve.log"),
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT + " [%(transferId)s]"))
        root.addHandler(handler)
    except OSError:
        # A read-only home directory must not stop an import.
        pass

    # Fusion's Console is the user-visible surface; keep it quiet by default.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(f"ffbridge.{name}")
