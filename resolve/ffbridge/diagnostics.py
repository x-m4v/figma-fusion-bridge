"""Diagnostics.

Every conversion that is not exact produces one of these. The design rule is
that a fallback path cannot be taken without emitting a diagnostic — the helper
functions require the message, so "silently approximated" is not expressible.

Messages are written for a designer: what happened, to which layer, and what to
do about it. Technical detail goes in ``detail`` and is shown only on request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"

_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.node_id:
            d["nodeId"] = self.node_id
        if self.node_name:
            d["nodeName"] = self.node_name
        if self.detail:
            d["detail"] = self.detail
        return d

    def format_line(self) -> str:
        glyph = {ERROR: "✕", WARNING: "⚠", INFO: "✓"}[self.severity]
        where = f' "{self.node_name}"' if self.node_name else ""
        return f"{glyph}{where} {self.message}" if where else f"{glyph} {self.message}"


@dataclass
class DiagnosticSink:
    items: List[Diagnostic] = field(default_factory=list)

    def info(self, code: str, message: str, **kw: Any) -> None:
        self.items.append(Diagnostic(INFO, code, message, **kw))

    def warn(self, code: str, message: str, **kw: Any) -> None:
        self.items.append(Diagnostic(WARNING, code, message, **kw))

    def error(self, code: str, message: str, **kw: Any) -> None:
        self.items.append(Diagnostic(ERROR, code, message, **kw))

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.items if d.severity == ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.items if d.severity == WARNING)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def sorted(self) -> List[Diagnostic]:
        """Errors first, then warnings, then info; stable within a severity."""
        return sorted(self.items, key=lambda d: _ORDER[d.severity])

    def to_list(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self.sorted()]

    def extend(self, other: "DiagnosticSink") -> None:
        self.items.extend(other.items)
