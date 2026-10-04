"""Serialiser for Fusion's ASCII composition format (``.setting`` / ``.comp``).

Why generate text instead of calling ``AddTool``/``SetInput``:

* One hand-off instead of thousands. A 150-layer frame needs roughly 2000
  ``SetInput`` calls, each a separate round-trip into the Fusion process.
* Structured values — ``Gradient{}``, ``Point{}``, ``StyledText{}`` — are
  expressible here exactly as Fusion writes them itself, and awkward or
  impossible to pass through the scripting bridge from Python.
* The generator becomes a pure function, so the whole conversion is testable
  with no Resolve running.

The grammar implemented here was taken from composition files shipped by
Blackmagic Design (``Templates.drfx`` and ``Developer/Fusion Templates``), not
from documentation, so what we emit is byte-compatible with what Fusion writes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

INDENT = "\t"


def _esc(s: str) -> str:
    """Escape a Python string into a Fusion/Lua double-quoted literal.

    Newlines must survive: multi-line Text+ content is a single ``StyledText``
    value containing ``\\n`` escapes, so writing a raw newline here would
    truncate the tool definition.
    """
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _num(v: float) -> str:
    """Format a number the way Fusion does: no exponent, no trailing noise."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return "0"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = f"{v:.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


class FuID:
    """A Fusion enum identifier, emitted as ``FuID { "Value" }``.

    A plain string would be emitted as a quoted string and silently ignored by
    Fusion for enum inputs, so enums get their own type rather than relying on
    the caller to remember.
    """

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def render(self) -> str:
        return "FuID { " + _esc(self.value) + " }"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"FuID({self.value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FuID) and other.value == self.value


class Point:
    """``Point { X = .., Y = .. }``. Used where Fusion expects a named pair."""

    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = float(x), float(y)

    def render(self) -> str:
        return "Point { X = " + _num(self.x) + ", Y = " + _num(self.y) + " }"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Point) and (other.x, other.y) == (self.x, self.y)


class Vec:
    """A positional tuple, emitted as ``{ a, b, ... }``.

    Distinct from :class:`Point` because Fusion accepts both forms in different
    inputs and mixing them up produces an input that silently keeps its default.
    ``Background.Start`` takes this form; ``TextPlus.Offset2`` takes either.
    """

    __slots__ = ("values",)

    def __init__(self, *values: float) -> None:
        self.values = tuple(float(v) for v in values)

    def render(self) -> str:
        return "{ " + ", ".join(_num(v) for v in self.values) + " }"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Vec) and other.values == self.values


class Gradient:
    """``Gradient { Colors = { [pos] = { r, g, b, a }, ... } }``.

    Positions are arbitrary floats, which is what lets an N-stop design gradient
    survive intact rather than being resampled to a fixed number of stops.
    Stops are sorted on render because Fusion reads them in file order and an
    out-of-order table produces a visibly wrong ramp.
    """

    __slots__ = ("stops",)

    def __init__(self, stops: Sequence[Tuple[float, Tuple[float, float, float, float]]]) -> None:
        self.stops = list(stops)

    def render(self, indent: str = "") -> str:
        rows = []
        for pos, rgba in sorted(self.stops, key=lambda s: s[0]):
            r, g, b, a = rgba
            rows.append(
                f"{indent}\t\t[{_num(pos)}] = {{ {_num(r)}, {_num(g)}, {_num(b)}, {_num(a)} }}"
            )
        body = ",\n".join(rows)
        return (
            "Gradient {\n"
            + indent
            + "\tColors = {\n"
            + body
            + "\n"
            + indent
            + "\t}\n"
            + indent
            + "}"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Gradient) and other.stops == self.stops


class Link:
    """An input driven by another tool's output: ``SourceOp`` + ``Source``.

    This is how the graph is wired. Fusion resolves the names at load time, so a
    link may legally point at a tool defined later in the file.
    """

    __slots__ = ("source_op", "source")

    def __init__(self, source_op: str, source: str = "Output") -> None:
        self.source_op = source_op
        self.source = source

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Link)
            and other.source_op == self.source_op
            and other.source == self.source
        )


class Expression:
    """A value plus a Fusion expression that drives it.

    Shipped Blackmagic content uses this (``Height = Input { Value = 0.05,
    Expression = "Width" }``), so it is a supported, round-trippable construct —
    the mechanism reserved for live Auto Layout.
    """

    __slots__ = ("value", "expression")

    def __init__(self, value: Any, expression: str) -> None:
        self.value = value
        self.expression = expression


def render_value(value: Any, indent: str = "") -> str:
    """Render any supported input value."""
    if isinstance(value, (FuID, Point, Vec)):
        return value.render()
    if isinstance(value, Gradient):
        return value.render(indent)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return _num(value)
    if isinstance(value, str):
        return _esc(value)
    if isinstance(value, (list, tuple)):
        return Vec(*value).render()
    raise TypeError(f"Cannot serialise {type(value).__name__} as a Fusion value")


class Tool:
    """One Fusion node.

    ``data`` becomes the node's persistent ``SetData`` payload. That is the
    anchor for re-sync: it travels with the node through save, load, copy and
    rename, which no name- or position-based scheme does.
    """

    def __init__(
        self,
        tool_id: str,
        name: str,
        inputs: Optional[Mapping[str, Any]] = None,
        pos: Tuple[float, float] = (0.0, 0.0),
        data: Optional[Mapping[str, Any]] = None,
        comments: str = "",
    ) -> None:
        self.tool_id = tool_id
        self.name = name
        self.inputs: Dict[str, Any] = dict(inputs or {})
        self.pos = pos
        self.data: Dict[str, Any] = dict(data or {})
        self.comments = comments

    def set(self, key: str, value: Any) -> "Tool":
        self.inputs[key] = value
        return self

    def render(self, indent: str) -> str:
        i = indent
        i2 = indent + INDENT
        i3 = i2 + INDENT
        lines: List[str] = [f"{i}{self.name} = {self.tool_id} {{"]

        # Loader media is a Clip record, not a scalar Input in saved settings.
        # Verified against Resolve 21.0.3 Loader.SaveSettings() and BMD templates.
        loader_clip = self.inputs.get("Clip") if self.tool_id == "Loader" else None
        if loader_clip is not None:
            if not isinstance(loader_clip, str) or not loader_clip:
                raise ValueError("Loader requires a non-empty asset path")
            import os
            formats = {".png": "PNGFormat", ".jpg": "JpegFormat", ".jpeg": "JpegFormat"}
            fmt = formats.get(os.path.splitext(loader_clip)[1].lower())
            if fmt is None:
                raise ValueError("Unverified Loader format: " + loader_clip)
            lines.extend([
                f"{i2}Clips = {{ Clip {{",
                f'{i3}ID = "Clip1",',
                f"{i3}Filename = {_esc(loader_clip)},",
                f"{i3}FormatID = {_esc(fmt)},",
                f"{i3}StartFrame = -1, LengthSetManually = true,",
                f"{i3}TrimIn = 0, TrimOut = 0, ExtendFirst = 0, ExtendLast = 0,",
                f"{i3}Loop = 1, AspectMode = 0, Depth = 0, TimeCode = 0,",
                f"{i3}GlobalStart = 0, GlobalEnd = 0,",
                f"{i2}}} }},",
            ])

        if self.inputs:
            lines.append(f"{i2}Inputs = {{")
            for key, val in self.inputs.items():
                if loader_clip is not None and key in ("Clip", "Loop", "GlobalIn"):
                    continue
                # Keys containing a dot are nested inputs and must be bracketed,
                # e.g. ["Translate.X"] — shipped content does exactly this.
                k = f'["{key}"]' if ("." in key or not key.isidentifier()) else key
                if isinstance(val, Link):
                    lines.append(f"{i3}{k} = Input {{")
                    lines.append(f"{i3}{INDENT}SourceOp = {_esc(val.source_op)},")
                    lines.append(f"{i3}{INDENT}Source = {_esc(val.source)},")
                    lines.append(f"{i3}}},")
                elif isinstance(val, Expression):
                    rendered = render_value(val.value, i3)
                    lines.append(f"{i3}{k} = Input {{")
                    lines.append(f"{i3}{INDENT}Value = {rendered},")
                    lines.append(f"{i3}{INDENT}Expression = {_esc(val.expression)},")
                    lines.append(f"{i3}}},")
                else:
                    # Point controls are positional pairs in saved settings.
                    rendered = Vec(val.x, val.y).render() if isinstance(val, Point) else render_value(val, i3)
                    if "\n" in rendered:
                        lines.append(f"{i3}{k} = Input {{")
                        lines.append(f"{i3}{INDENT}Value = {rendered},")
                        lines.append(f"{i3}}},")
                    else:
                        lines.append(f"{i3}{k} = Input {{ Value = {rendered}, }},")
            lines.append(f"{i2}}},")

        if self.data:
            lines.append(f"{i2}CustomData = {{")
            lines.append(f"{i3}FFBridge = {{")
            for key, val in self.data.items():
                lines.append(f"{i3}{INDENT}{key} = {render_value(val, i3)},")
            lines.append(f"{i3}}},")
            lines.append(f"{i2}}},")

        if self.comments:
            lines.append(f"{i2}Comments = {_esc(self.comments)},")

        lines.append(f"{i2}ViewInfo = OperatorInfo {{ Pos = {{ {_num(self.pos[0])}, {_num(self.pos[1])} }} }},")
        lines.append(f"{i}}},")
        return "\n".join(lines)


class CompDocument:
    """A whole Fusion composition fragment, ready to paste or import."""

    def __init__(self) -> None:
        self.tools: List[Tool] = []
        self._names: Dict[str, Tool] = {}
        self.active_tool: Optional[str] = None

    def add(self, tool: Tool) -> Tool:
        if tool.name in self._names:
            raise ValueError(f"Duplicate Fusion tool name {tool.name!r}")
        self.tools.append(tool)
        self._names[tool.name] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return self._names.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def __len__(self) -> int:
        return len(self.tools)

    def render(self) -> str:
        lines = ["{", f"{INDENT}Tools = ordered() {{"]
        for tool in self.tools:
            lines.append(tool.render(INDENT * 2))
        lines.append(f"{INDENT}}},")
        if self.active_tool:
            lines.append(f"{INDENT}ActiveTool = {_esc(self.active_tool)}")
        lines.append("}")
        return "\n".join(lines) + "\n"
