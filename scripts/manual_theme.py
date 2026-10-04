"""Typography, colour and page furniture for the PDF manual.

Kept apart from the content so the manual reads as one document rather than a
stack of styled fragments, and so a change of palette is one edit.
"""

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm

PAGE = A4
PAGE_W, PAGE_H = PAGE

MARGIN_L = 24 * mm
MARGIN_R = 20 * mm
MARGIN_T = 22 * mm
MARGIN_B = 20 * mm

# A restrained palette. One accent, used for structure rather than decoration,
# so warnings and notes still read as exceptional when they appear.
INK = colors.HexColor("#15161A")
INK_SOFT = colors.HexColor("#4A4D57")
INK_FAINT = colors.HexColor("#8A8D98")
ACCENT = colors.HexColor("#3B5BDB")
ACCENT_SOFT = colors.HexColor("#E7ECFD")
RULE = colors.HexColor("#DDDFE6")
SURFACE = colors.HexColor("#F5F6F9")
CODE_BG = colors.HexColor("#F2F3F7")
WARN = colors.HexColor("#B7791F")
WARN_BG = colors.HexColor("#FDF6E5")
OK = colors.HexColor("#1F9254")
OK_BG = colors.HexColor("#EAF7F0")
COVER_BG = colors.HexColor("#14161C")

BODY_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"
ITALIC_FONT = "Helvetica-Oblique"
MONO_FONT = "Courier"
MONO_BOLD = "Courier-Bold"


def build_styles():
    styles = getSampleStyleSheet()

    def add(name, **kw):
        # Guard against clashing with reportlab's own sample styles.
        assert name not in styles.byName, f"style {name!r} already exists"
        styles.add(ParagraphStyle(name=name, **kw))

    add("CoverTitle", fontName=BOLD_FONT, fontSize=40, leading=44,
        textColor=colors.white, alignment=TA_LEFT, spaceAfter=6)
    add("CoverTagline", fontName=BODY_FONT, fontSize=15, leading=22,
        textColor=colors.HexColor("#A9AEBD"), alignment=TA_LEFT)
    add("CoverMeta", fontName=BODY_FONT, fontSize=9.5, leading=15,
        textColor=colors.HexColor("#6E7385"), alignment=TA_LEFT)

    add("H1", fontName=BOLD_FONT, fontSize=21, leading=25, textColor=INK,
        spaceBefore=0, spaceAfter=10)
    add("H1Num", fontName=BOLD_FONT, fontSize=10, leading=12, textColor=ACCENT,
        spaceAfter=3, spaceBefore=0)
    add("H2", fontName=BOLD_FONT, fontSize=13, leading=17, textColor=INK,
        spaceBefore=14, spaceAfter=5)
    add("H3", fontName=BOLD_FONT, fontSize=10.5, leading=14, textColor=INK_SOFT,
        spaceBefore=10, spaceAfter=3)

    add("Body", fontName=BODY_FONT, fontSize=9.6, leading=14.6, textColor=INK,
        alignment=TA_JUSTIFY, spaceAfter=7)
    add("Lead", fontName=BODY_FONT, fontSize=11, leading=17, textColor=INK_SOFT,
        alignment=TA_LEFT, spaceAfter=10)
    add("ListItem", fontName=BODY_FONT, fontSize=9.6, leading=14.2, textColor=INK,
        leftIndent=11, bulletIndent=2, spaceAfter=3.5)
    add("Caption", fontName=BODY_FONT, fontSize=8.2, leading=11.5,
        textColor=INK_FAINT, spaceBefore=3, spaceAfter=9)

    add("CodeBlock", fontName=MONO_FONT, fontSize=8.1, leading=11.6, textColor=INK,
        backColor=CODE_BG, borderPadding=(7, 8, 7, 8), spaceBefore=3, spaceAfter=9)
    add("Callout", fontName=BODY_FONT, fontSize=9.2, leading=13.6, textColor=INK,
        leftIndent=9, rightIndent=6, spaceBefore=2, spaceAfter=2)
    add("CalloutLabel", fontName=BOLD_FONT, fontSize=7.6, leading=10,
        textColor=WARN, spaceAfter=2)

    add("TableHead", fontName=BOLD_FONT, fontSize=8.3, leading=11, textColor=colors.white)
    add("TableCell", fontName=BODY_FONT, fontSize=8.3, leading=11.6, textColor=INK)
    add("TableCode", fontName=MONO_FONT, fontSize=7.8, leading=11.2, textColor=INK)

    add("TOC1", fontName=BOLD_FONT, fontSize=9.6, leading=17, textColor=INK)
    add("TOC2", fontName=BODY_FONT, fontSize=9, leading=14, textColor=INK_SOFT,
        leftIndent=14)
    return styles
