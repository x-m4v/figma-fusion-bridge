"""Custom page furniture: callouts, tables, and the architecture diagrams.

The diagrams are drawn rather than screenshotted so they stay sharp at any zoom
and can be regenerated when the architecture changes.
"""

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

from manual_theme import (
    ACCENT, ACCENT_SOFT, CODE_BG, INK, INK_FAINT, INK_SOFT, MONO_FONT, OK, OK_BG,
    RULE, SURFACE, WARN, WARN_BG, BODY_FONT, BOLD_FONT,
)


class HRule(Flowable):
    """A hairline. Used to separate a section head from its body."""

    def __init__(self, width, thickness=0.6, color=RULE, space=4):
        super().__init__()
        self.width, self.thickness, self.color, self.space = width, thickness, color, space

    def wrap(self, *_):
        return (self.width, self.thickness + self.space)

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.space, self.width, self.space)


def callout(styles, kind, text, width):
    """A tip, note or warning.

    Colour-coded and labelled, so the label carries the meaning for anyone
    reading in greyscale or with impaired colour vision.
    """
    palette = {
        "TIP": (OK, OK_BG, "TIP"),
        "NOTE": (ACCENT, ACCENT_SOFT, "NOTE"),
        "WARNING": (WARN, WARN_BG, "IMPORTANT"),
    }
    stroke, fill, label = palette.get(kind, palette["NOTE"])
    label_style = styles["CalloutLabel"].clone("cl")
    label_style.textColor = stroke

    inner = [
        [Paragraph(label, label_style)],
        [Paragraph(text, styles["Callout"])],
    ]
    table = Table(inner, colWidths=[width - 6 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, stroke),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 7),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 1), (0, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
    ]))
    return KeepTogether([Spacer(1, 3), table, Spacer(1, 9)])


def data_table(styles, header, rows, widths, mono_columns=()):
    """A table that reads as data rather than as a grid."""
    head_cells = [Paragraph(h, styles["TableHead"]) for h in header]
    body = [head_cells]
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            style = styles["TableCode"] if i in mono_columns else styles["TableCell"]
            cells.append(Paragraph(str(cell), style))
        body.append(cells)

    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
    ]
    # Banding rather than gridlines: fewer marks, same scannability.
    for i in range(1, len(body)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), SURFACE))
    table.setStyle(TableStyle(style))
    # Deliberately not wrapped in KeepTogether: `repeatRows=1` carries the
    # header onto the next page, so letting a long table split is better
    # typography than pushing the whole thing over and leaving half a page blank.
    return [Spacer(1, 2), table, Spacer(1, 10)]


class PipelineDiagram(Flowable):
    """The four-stage pipeline, drawn as boxes and arrows."""

    STAGES = [
        ("Figma", "plugin reads\nthe selection"),
        ("Bridge", "127.0.0.1 only\nnever the network"),
        ("Resolve", "script fetches\nand validates"),
        ("Fusion", "native, editable\nnode graph"),
    ]

    def __init__(self, width, height=34 * mm):
        super().__init__()
        self.width, self.height = width, height

    def wrap(self, *_):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        n = len(self.STAGES)
        gap = 9 * mm
        box_w = (self.width - gap * (n - 1)) / n
        box_h = 21 * mm
        y = self.height - box_h - 3 * mm

        for i, (title, subtitle) in enumerate(self.STAGES):
            x = i * (box_w + gap)
            c.setFillColor(SURFACE)
            c.setStrokeColor(RULE)
            c.setLineWidth(0.6)
            c.roundRect(x, y, box_w, box_h, 3, stroke=1, fill=1)

            c.setFillColor(ACCENT)
            c.setFont(BOLD_FONT, 9)
            c.drawCentredString(x + box_w / 2, y + box_h - 8 * mm, title)

            c.setFillColor(INK_SOFT)
            c.setFont(BODY_FONT, 6.6)
            for j, line in enumerate(subtitle.split("\n")):
                c.drawCentredString(x + box_w / 2, y + box_h - 12.5 * mm - j * 3.4 * mm, line)

            if i < n - 1:
                ax = x + box_w + 1.6 * mm
                ay = y + box_h / 2
                c.setStrokeColor(ACCENT)
                c.setFillColor(ACCENT)
                c.setLineWidth(1.1)
                c.line(ax, ay, ax + gap - 4.6 * mm, ay)
                tip = ax + gap - 3.2 * mm
                c.setLineWidth(0)
                p = c.beginPath()
                p.moveTo(tip, ay)
                p.lineTo(tip - 2.1 * mm, ay + 1.35 * mm)
                p.lineTo(tip - 2.1 * mm, ay - 1.35 * mm)
                p.close()
                c.drawPath(p, fill=1, stroke=0)

        c.setFillColor(INK_FAINT)
        c.setFont(BODY_FONT, 6.8)
        c.drawCentredString(self.width / 2, 1.5 * mm,
                            "Structured design data at every step — never a rendered image.")


class BranchDiagram(Flowable):
    """How one design layer becomes a branch of Fusion nodes."""

    NODES = [
        ("CTA_Button_Shape", "sRectangle", False),
        ("CTA_Button_Fill", "sRender", False),
        ("CTA_Button_Shadow", "Shadow", False),
        ("CTA_Button_Anim", "Transform", True),
        ("Root_Merge", "Merge", False),
    ]

    def __init__(self, width, height=30 * mm):
        super().__init__()
        self.width, self.height = width, height

    def wrap(self, *_):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        n = len(self.NODES)
        gap = 4.5 * mm
        box_w = (self.width - gap * (n - 1)) / n
        box_h = 15 * mm
        y = self.height - box_h - 6 * mm

        for i, (name, kind, is_user) in enumerate(self.NODES):
            x = i * (box_w + gap)
            c.setFillColor(OK_BG if is_user else SURFACE)
            c.setStrokeColor(OK if is_user else RULE)
            c.setLineWidth(1.2 if is_user else 0.6)
            c.roundRect(x, y, box_w, box_h, 2.5, stroke=1, fill=1)

            c.setFillColor(INK)
            c.setFont(BOLD_FONT, 6.2)
            c.drawCentredString(x + box_w / 2, y + box_h - 6 * mm, name)
            c.setFillColor(INK_FAINT)
            c.setFont(MONO_FONT, 6)
            c.drawCentredString(x + box_w / 2, y + box_h - 9.6 * mm, kind)

            if i < n - 1:
                ax = x + box_w + 0.8 * mm
                ay = y + box_h / 2
                c.setStrokeColor(INK_FAINT)
                c.setLineWidth(0.8)
                c.line(ax, ay, ax + gap - 1.6 * mm, ay)

        c.setFillColor(OK)
        c.setFont(BOLD_FONT, 6.6)
        c.drawCentredString(3 * (box_w + gap) + box_w / 2, y - 4.2 * mm,
                            "your keyframes live here — re-sync never writes to it")
