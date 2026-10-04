#!/usr/bin/env python3
"""Builds the Figma Fusion Bridge PDF manual.

A typeset document rather than a converted README: cover, generated table of
contents, running headers, page numbers, drawn diagrams, and tables that read as
data. Run with `make pdf`.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Preformatted, Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

from manual_flowables import BranchDiagram, HRule, PipelineDiagram, callout, data_table
from manual_theme import (
    ACCENT, BODY_FONT, BOLD_FONT, COVER_BG, INK, INK_FAINT, INK_SOFT, MARGIN_B,
    MARGIN_L, MARGIN_R, MARGIN_T, MONO_FONT, PAGE, PAGE_H, PAGE_W, RULE,
    build_styles,
)

VERSION = "1.0"
PRODUCT = "Figma Fusion Bridge"
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

styles = build_styles()


# ---------------------------------------------------------------------------
# Document template
# ---------------------------------------------------------------------------

class Manual(BaseDocTemplate):
    """Two page templates: a full-bleed cover, and the body with furniture."""

    def __init__(self, path):
        super().__init__(
            path, pagesize=PAGE,
            leftMargin=MARGIN_L, rightMargin=MARGIN_R,
            topMargin=MARGIN_T, bottomMargin=MARGIN_B,
            title=f"{PRODUCT} Manual", author=PRODUCT,
            subject="Design in Figma. Animate in Fusion.",
            creator=PRODUCT,
        )
        self.current_section = ""
        frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W,
                      PAGE_H - MARGIN_T - MARGIN_B, id="body")
        cover_frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W,
                            PAGE_H - MARGIN_T - MARGIN_B, id="cover")
        self.addPageTemplates([
            PageTemplate(id="Cover", frames=[cover_frame], onPage=self.draw_cover),
            # Drawn at page *end*, not page start. `onPage` fires before any
            # flowable is laid out, so the running header would still hold the
            # previous section's title on the page where a new section begins.
            PageTemplate(id="Body", frames=[frame], onPageEnd=self.draw_body),
        ])

    # -- page furniture ----------------------------------------------------

    def draw_cover(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(COVER_BG)
        canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

        # A restrained graphic mark, sitting in the empty band between the
        # tagline and the imprint. Positioned above the metadata block rather
        # than behind it — decoration must not cross type.
        canvas.setStrokeColor(colors.HexColor("#2A2E3A"))
        canvas.setLineWidth(0.8)
        for i in range(13):
            y = PAGE_H * 0.50 - i * 4.2 * mm
            canvas.line(MARGIN_L, y, PAGE_W - MARGIN_R - i * 6 * mm, y)

        canvas.setFillColor(ACCENT)
        canvas.rect(MARGIN_L, PAGE_H - 62 * mm, 26 * mm, 1.6 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def draw_body(self, canvas, doc):
        canvas.saveState()
        # Running header: product on the left, current section on the right.
        canvas.setFont(BODY_FONT, 7.4)
        canvas.setFillColor(INK_FAINT)
        canvas.drawString(MARGIN_L, PAGE_H - MARGIN_T + 7 * mm, PRODUCT)
        if self.current_section:
            canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 7 * mm,
                                   self.current_section)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN_L, PAGE_H - MARGIN_T + 5 * mm,
                    PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 5 * mm)

        # Footer: version on the left, page number on the right.
        canvas.line(MARGIN_L, MARGIN_B - 6 * mm, PAGE_W - MARGIN_R, MARGIN_B - 6 * mm)
        canvas.setFont(BODY_FONT, 7.4)
        canvas.drawString(MARGIN_L, MARGIN_B - 10.5 * mm, f"Version {VERSION}")
        canvas.setFont(BOLD_FONT, 8)
        canvas.setFillColor(INK_SOFT)
        canvas.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 10.5 * mm, str(doc.page - 1))
        canvas.restoreState()

    # -- table of contents -------------------------------------------------

    def afterFlowable(self, flowable):
        """Feed headings to the TOC and to the running header."""
        if not isinstance(flowable, Paragraph):
            return
        name = flowable.style.name
        if name == "H1":
            text = flowable.getPlainText()
            self.current_section = text
            self.notify("TOCEntry", (0, text, self.page - 1))
        elif name == "H2":
            self.notify("TOCEntry", (1, flowable.getPlainText(), self.page - 1))


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------

story = []
_section_no = [0]


def section(title, lead=None):
    _section_no[0] += 1
    story.append(PageBreak())
    story.append(Paragraph(f"{_section_no[0]:02d}", styles["H1Num"]))
    story.append(Paragraph(title, styles["H1"]))
    story.append(HRule(CONTENT_W))
    if lead:
        story.append(Paragraph(lead, styles["Lead"]))


def h2(text):
    story.append(Paragraph(text, styles["H2"]))


def h3(text):
    story.append(Paragraph(text, styles["H3"]))


def p(text):
    story.append(Paragraph(text, styles["Body"]))


def bullets(items):
    for item in items:
        story.append(Paragraph(item, styles["ListItem"], bulletText="•"))
    story.append(Spacer(1, 6))


def steps(items):
    for i, item in enumerate(items, 1):
        story.append(Paragraph(item, styles["ListItem"], bulletText=f"{i}."))
    story.append(Spacer(1, 6))


def code(text):
    story.append(Preformatted(text.strip("\n"), styles["CodeBlock"]))


def caption(text):
    story.append(Paragraph(text, styles["Caption"]))


def note(text, kind="NOTE"):
    story.append(callout(styles, kind, text, CONTENT_W))


def table(header, rows, widths, mono=()):
    story.extend(data_table(styles, header, rows, widths, mono))


def gap(h=6):
    story.append(Spacer(1, h))


# ---------------------------------------------------------------------------
# Cover and contents
# ---------------------------------------------------------------------------

story.append(Spacer(1, 74 * mm))
story.append(Paragraph(PRODUCT, styles["CoverTitle"]))
story.append(Spacer(1, 4 * mm))
story.append(Paragraph("Design in Figma.<br/>Animate in Fusion.", styles["CoverTagline"]))
story.append(Spacer(1, 86 * mm))
story.append(Paragraph(
    f"Version {VERSION} &nbsp;·&nbsp; macOS, Apple Silicon<br/>"
    f"For DaVinci Resolve 21 &nbsp;·&nbsp; Interchange schema 1.0.0<br/>"
    f"{date.today().isoformat()}",
    styles["CoverMeta"]))

story.append(NextPageTemplate("Body"))
story.append(PageBreak())

story.append(Paragraph("Contents", styles["H1"]))
story.append(HRule(CONTENT_W))
toc = TableOfContents()
toc.levelStyles = [styles["TOC1"], styles["TOC2"]]
toc.dotsMinLevel = 0
story.append(toc)


# ---------------------------------------------------------------------------
# 1. What it is
# ---------------------------------------------------------------------------

section(
    "What is Figma Fusion Bridge?",
    "It sends the structure of a design from Figma to DaVinci Resolve, so Fusion "
    "receives real tools to animate rather than a picture to trace over.",
)

p("Motion work that starts in Figma usually starts twice. The designer builds a "
  "screen; the motion designer exports it as flat images, or rebuilds the layout "
  "by hand in Fusion. Then the design changes, and the second build starts again.")

p("This tool removes the second build. You select a frame in Figma, press one "
  "button, and run Receive in Resolve. What arrives is a structured node graph: "
  "rounded rectangles whose radius you can still drag, gradients whose stops you "
  "can still move, and text you can retype.")

story.append(PipelineDiagram(CONTENT_W))
caption("Four processes, one direction. Structured design data at every step.")

h2("The rule the whole product follows")
p("<b>Design data, not screenshots.</b> A layer is rasterised only when it "
  "genuinely cannot be rebuilt with native Fusion tools — and when that happens, "
  "the transfer log names the layer and says why. Nothing is quietly flattened, "
  "approximated or substituted.")

note("Everything stays on your Mac. The bridge listens on the loopback "
     "interface and nothing else. There is no account, no cloud service and no telemetry in the "
     "transfer path.", "TIP")


# ---------------------------------------------------------------------------
# 2. Why use it
# ---------------------------------------------------------------------------

section("Why use it?")

table(
    ["Instead of", "You get"],
    [
        ["Exporting PNGs and animating on top of them",
         "Native Fusion shapes that stay sharp at any resolution"],
        ["Rebuilding layouts by hand in Fusion",
         "Hierarchy, z-order and positions arriving correct the first time"],
        ["Re-typing copy in a title tool",
         "Real <font face='Courier'>Text+</font> you can edit in Resolve"],
        ["Baking gradients into images",
         "Editable gradients with every stop and its alpha"],
        ["Redoing the animation when the design changes",
         "A re-sync that updates the design and leaves your keyframes alone"],
        ["Guessing which layers did not survive",
         "A transfer log naming every approximation"],
    ],
    [CONTENT_W * 0.44, CONTENT_W * 0.56],
)

h2("What it is not")
p("It is not a renderer, and it is not a way to make Fusion behave like Figma. "
  "Some things genuinely have no equivalent — non-separable blend modes, dashed "
  "strokes, corner smoothing. Those are listed plainly in Limitations, and the "
  "tool warns you at transfer time rather than letting you discover them later.")


# ---------------------------------------------------------------------------
# 3. Requirements
# ---------------------------------------------------------------------------

section("System requirements")

table(
    ["Component", "Requirement", "Notes"],
    [
        ["macOS", "14 or later", "Tested on macOS 27"],
        ["Mac", "Apple Silicon", "Native arm64 — Rosetta is not used"],
        ["DaVinci Resolve", "21", "Verified against 21.0.3, Free and Studio"],
        ["Figma", "Desktop or browser", "Both work; the bridge is local either way"],
        ["Node.js", "20 or later", "To build from source only"],
        ["Swift", "5.9 or later", "Command Line Tools are enough — no Xcode"],
    ],
    [CONTENT_W * 0.24, CONTENT_W * 0.26, CONTENT_W * 0.50],
)

note("Features that need DaVinci Resolve Studio are marked in this manual. "
     "The Receive workflow is designed to work in the free edition: Resolve pulls "
     "work from the bridge using a script you launch from its own menu, rather "
     "than being driven from outside.", "NOTE")


# ---------------------------------------------------------------------------
# 4. Installation
# ---------------------------------------------------------------------------

section("Installation", "Three pieces: the app, the Resolve scripts, and the Figma plugin.")

h2("Build and start the bridge")
code("npm install\nmake build\nopen \"dist/Figma Fusion Bridge.app\"")
p("The app lives in the menu bar and has no Dock icon. Confirm it is listening:")
code("curl http://127.0.0.1:8787/api/hello\n"
     '{"app":"figma-fusion-bridge","schemaVersion":"1.0.0","paired":false,"version":"0.1.0"}')

h2("Install the Resolve scripts")
p("In the app, open <b>Setup</b> and press <b>Install scripts</b>. They are "
  "written to your own Application Support folder, so no administrator password "
  "is needed:")
code("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/\n"
     "  Comp/Figma Fusion Bridge/Receive.py\n"
     "  Comp/Figma Fusion Bridge/Receive Into Current Composition.py\n"
     "  Comp/Figma Fusion Bridge/Pull Current Figma Selection.py\n"
     "  Utility/Figma Fusion Bridge/Connection Test.py")

note("Restart DaVinci Resolve if it was already running. Resolve scans its "
     "Scripts folder once, at startup — this is by far the most common reason the "
     "menu entries do not appear.", "WARNING")

h2("Install the Figma plugin")
p("Figma does not allow plugins to be installed programmatically, so this step is "
  "manual — once.")
steps([
    "In Figma: <b>Plugins → Development → Import plugin from manifest…</b>",
    "Choose <font face='Courier'>packages/figma-plugin/manifest.json</font>.",
    "The plugin appears under <b>Plugins → Development</b>.",
])

h2("Pair")
p("Run the plugin, read the six-character code from the app's <b>Status</b> tab, "
  "and type it in. The plugin stores the resulting token, so this happens once.")
p("The code expires after ten minutes and is regenerated each time the app "
  "launches. That is deliberate: a loopback port is reachable from any web page "
  "you have open, so the port alone is not a permission.")


# ---------------------------------------------------------------------------
# 5. Quick start
# ---------------------------------------------------------------------------

section("Quick start")

steps([
    "In Figma, select a frame — a card, a button, a whole screen.",
    "Open the plugin and press <b>Send to Fusion</b>.",
    "Read the transfer log. Fix anything it warns about now, while you are still in Figma.",
    "In Resolve, open a clip on the Fusion page.",
    "<b>Workspace → Scripts → Figma Fusion Bridge - Receive.</b>",
    "Animate — on the <font face='Courier'>*_Anim</font> Transform of each layer.",
    "Change the design in Figma and press Send again.",
    "Run Receive once more. The design updates; your keyframes stay.",
])

note("Step 6 is the one worth remembering. Every imported layer gets its own "
     "Transform node named <font face='Courier'>*_Anim</font>, and re-sync has no "
     "code path that writes to it.", "TIP")


# ---------------------------------------------------------------------------
# 6. The Figma plugin
# ---------------------------------------------------------------------------

section("The Figma plugin")

table(
    ["Control", "What it does"],
    [
        ["Status lights", "Bridge, DaVinci Resolve and Fusion. Green means ready."],
        ["Selection card", "What will be sent, and how many layers it contains."],
        ["Send to Fusion", "Reads the selection, uploads new assets, queues the transfer."],
        ["Live Sync", "Re-sends automatically after each edit, debounced by about a second."],
        ["Options", "Vector strategy, clipping, colour handling, hidden layers."],
        ["Transfer log", "Every warning, by layer name."],
    ],
    [CONTENT_W * 0.26, CONTENT_W * 0.74],
)

h2("Options in detail")
table(
    ["Option", "Choices", "Effect"],
    [
        ["Vector shapes", "Native only · Automatic · Always image",
         "How hard to try rebuilding paths as Fusion shapes. Automatic is right almost always."],
        ["Clip frames", "Follow Figma · Always · Never",
         "Whether frame contents are clipped to the frame bounds."],
        ["Colour", "Match Figma · Use project colour",
         "See Colour management."],
        ["Preserve hierarchy", "on / off",
         "Off flattens everything to one level. Rarely what you want."],
        ["Include hidden layers", "off by default",
         "Hidden layers are usually hidden on purpose."],
        ["Flatten unsupported", "on by default",
         "Export what cannot be rebuilt, rather than skipping it entirely."],
    ],
    [CONTENT_W * 0.20, CONTENT_W * 0.30, CONTENT_W * 0.50],
)


# ---------------------------------------------------------------------------
# 7. The macOS bridge
# ---------------------------------------------------------------------------

section("The macOS bridge")

p("A background utility. It has no Dock icon by design — look for the branch "
  "icon in the menu bar.")

h2("Tabs")
bullets([
    "<b>Status</b> — connection lights, the port in use, and the pairing code.",
    "<b>Setup</b> — a three-step checklist: Resolve, scripts, plugin.",
    "<b>History</b> — recent transfers with node counts, timings and warnings.",
    "<b>Settings</b> — asset cache size and clearing, unpairing, log access.",
])

h2("Where it keeps things")
table(
    ["What", "Where"],
    [
        ["Assets", "~/Library/Application Support/FigmaFusionBridge/Assets"],
        ["Transfers", "~/Library/Application Support/FigmaFusionBridge/Transfers"],
        ["Manifests", "~/Library/Application Support/FigmaFusionBridge/Manifests"],
        ["Session token", "~/Library/Application Support/FigmaFusionBridge/session.json"],
        ["Logs", "~/Library/Logs/FigmaFusionBridge/"],
    ],
    [CONTENT_W * 0.24, CONTENT_W * 0.76],
    mono=(1,),
)

p("Assets live in Application Support rather than a temporary folder on purpose: "
  "a Fusion Loader stores a <i>path</i>, so assets in "
  "<font face='Courier'>/tmp</font> would break every existing composition the "
  "next time macOS swept it.")


# ---------------------------------------------------------------------------
# 8. DaVinci Resolve
# ---------------------------------------------------------------------------

section("Receiving in DaVinci Resolve")

table(
    ["Command", "What it does"],
    [
        ["Receive", "Brings in the latest transfer."],
        ["Receive Into Current Composition",
         "Adds it to the composition you have open, leaving the existing graph "
         "untouched. Re-running it updates the layers it created before instead "
         "of duplicating them."],
        ["Pull Current Figma Selection",
         "Asks Figma for whatever is selected right now, without leaving Resolve."],
        ["Connection Test",
         "Checks every link in the chain and names the broken one."],
    ],
    [CONTENT_W * 0.34, CONTENT_W * 0.66],
)

h2("The transfer report")
code("""──────────────────────────────────────────────────────────
  Figma Fusion Bridge — Received
──────────────────────────────────────────────────────────
  20 nodes · 1 assets · 34 ms
  Import path: paste · Composition: 1920x1080

  ⚠ "Headline" The font "Neue Haas Grotesk Display Pro" is
    not installed on this Mac. Text is created with the
    original font name, so installing the font makes it
    appear correctly without re-importing.
  ✓ 2 layer(s) updated, 1 added, 0 no longer in the design.

  0 error(s), 1 warning(s)""")

h2("Reading the node graph")
story.append(BranchDiagram(CONTENT_W))
caption("One design layer becomes one branch. Node names come from your layer names.")

p("The composite chain runs left to right along a single row; each layer "
  "contributes a branch above it, built in the order the pixels flow. The suffix "
  "tells you what a node is: <font face='Courier'>_Shape</font>, "
  "<font face='Courier'>_Stroke</font>, <font face='Courier'>_Fill</font>, "
  "<font face='Courier'>_Shadow</font>, <font face='Courier'>_Anim</font>, "
  "<font face='Courier'>_Merge</font>.")


# ---------------------------------------------------------------------------
# 9. Supported elements
# ---------------------------------------------------------------------------

section("Supported elements",
        "Full means it matches and stays editable. Computed means the exact result, "
        "reached by constructing geometry. Approximate and Experimental are always "
        "warned at transfer time.")

h2("Shapes")
table(
    ["Figma", "Fusion", "Support"],
    [
        ["Rectangle", "sRectangle", "Full"],
        ["Rounded rectangle", "sRectangle + CornerRadius", "Full"],
        ["Per-corner radii", "sRectangle", "Approximate"],
        ["Ellipse", "sEllipse", "Full"],
        ["Polygon", "sNGon", "Full"],
        ["Star", "sStar", "Full"],
        ["Line", "sRectangle + stroke", "Full"],
        ["Custom vector path", "SVG asset", "Approximate"],
        ["Boolean operation", "SVG asset", "Approximate"],
    ],
    [CONTENT_W * 0.34, CONTENT_W * 0.36, CONTENT_W * 0.30],
    mono=(1,),
)

h2("Paint and stroke")
table(
    ["Figma", "Fusion", "Support"],
    [
        ["Solid fill", "Shape colour", "Full"],
        ["Linear gradient", "Background gradient", "Full"],
        ["Radial gradient", "Background radial", "Full"],
        ["Angular gradient", "Background angle", "Approximate"],
        ["Diamond gradient", "Background square", "Approximate"],
        ["Image fill", "Loader + Transform", "Full"],
        ["Solid stroke", "Second shape, Solid = 0", "Full"],
        ["Gradient stroke", "Shape masking a gradient", "Full"],
        ["INSIDE / OUTSIDE stroke", "Offset path", "Computed"],
        ["Dashed stroke", "Solid stroke", "Unsupported"],
    ],
    [CONTENT_W * 0.34, CONTENT_W * 0.36, CONTENT_W * 0.30],
    mono=(1,),
)

h2("Text and effects")
table(
    ["Figma", "Fusion", "Support"],
    [
        ["Characters, multi-line", "Text+ StyledText", "Full"],
        ["Font family and style", "Font / Style", "Full"],
        ["Size, tracking, leading", "Size, CharacterSpacing, LineSpacing", "Full"],
        ["Alignment", "…JustificationNew", "Full"],
        ["Mixed styles in one layer", "One Text+, dominant style", "Approximate"],
        ["Drop shadow", "Shadow", "Full"],
        ["Layer blur", "Blur", "Full"],
        ["Inner shadow", "matte → invert → blur → merge", "Computed"],
        ["Background blur", "branch and re-merge", "Experimental"],
    ],
    [CONTENT_W * 0.34, CONTENT_W * 0.36, CONTENT_W * 0.30],
    mono=(1,),
)


# ---------------------------------------------------------------------------
# 10. Live Sync
# ---------------------------------------------------------------------------

section("Live Sync")

p("Three ways to send. <b>Manual</b> is the default: you press Send. "
  "<b>Auto</b> and <b>Live</b> re-send after each edit, debounced by about a "
  "second.")

p("Debounced rather than throttled, deliberately. Dragging a layer emits a "
  "continuous stream of changes, and what you want sent is where the layer ended "
  "up — not thirty intermediate positions. Sending on the trailing edge also "
  "keeps Fusion from being asked to rebuild a graph many times a second.")

h2("How a layer is recognised on the second send")
p("By its Figma layer id, stored on each Fusion node using Fusion's own "
  "per-node data. Never by name, position or order — all three are things a "
  "motion designer legitimately changes, and a tool that read identity from them "
  "would destroy work the first time someone renamed a node.")

table(
    ["In Figma", "In Fusion"],
    [
        ["Layer changed", "Its source nodes are rebuilt; its Anim transform is untouched"],
        ["Layer added", "A new branch is created and merged in z-order"],
        ["Layer renamed", "Recognised; nothing is duplicated"],
        ["Layers reordered", "Merge order updated"],
        ["Layer deleted", "Its Fusion nodes are <b>kept</b>, with a warning"],
    ],
    [CONTENT_W * 0.26, CONTENT_W * 0.74],
)

note("Deleted layers are kept rather than removed. An accidental deletion in "
     "Figma must not destroy an evening's animation. Delete them by hand when you "
     "are sure.", "TIP")


# ---------------------------------------------------------------------------
# 11. Preserving animation
# ---------------------------------------------------------------------------

section("Preserving your animation")

p("Every imported layer gets its own Transform node, named "
  "<font face='Courier'>*_Anim</font>. It is created once and then belongs to "
  "you: the sync has no code path that writes to it. That single node is the "
  "whole animation-preservation strategy.")

h2("Safe after a re-sync")
bullets([
    "Keyframes on any <font face='Courier'>*_Anim</font> node",
    "Nodes you added yourself, anywhere in the graph",
    "Anything downstream of the imported graph",
])

h2("Rebuilt by a re-sync — do not animate these directly")
bullets([
    "<font face='Courier'>*_Shape</font>, <font face='Courier'>*_Stroke</font>, "
    "<font face='Courier'>*_Fill</font> — geometry comes from the design",
    "<font face='Courier'>*_Shadow</font>, <font face='Courier'>*_Blur</font> — "
    "effect settings come from the design",
    "<font face='Courier'>*_Merge</font> — reconnected, with Blend and ApplyMode refreshed",
])

note("If you have already animated a <font face='Courier'>*_Shape</font> node, "
     "move those keyframes to the layer's <font face='Courier'>*_Anim</font> "
     "Transform before your next sync.", "WARNING")


# ---------------------------------------------------------------------------
# 12. Colour
# ---------------------------------------------------------------------------

section("Colour management")

p("Figma works in sRGB. A Resolve project may be Rec.709, DaVinci Wide Gamut, "
  "ACES or an HDR space, and a Fusion composition inherits that. So the RGB "
  "numbers from Figma are not unconditionally the numbers Fusion should receive, "
  "and assuming they are is how a brand colour arrives visibly wrong.")

table(
    ["Setting", "What it does", "Use when"],
    [
        ["Match Figma (sRGB)", "Values pass through unchanged",
         "Plain DaVinci YRGB. What you see in Figma is what you get."],
        ["Use project colour",
         "Linearised with the exact sRGB transfer function, then handed to Resolve's colour management",
         "DaVinci YRGB Color Managed, or ACES."],
    ],
    [CONTENT_W * 0.22, CONTENT_W * 0.42, CONTENT_W * 0.36],
)

p("The exact sRGB curve is used, not the 2.2 power approximation. The "
  "approximation is off by up to about half a percent in the shadows, which is "
  "visible as a colour shift on the dark surfaces that interface design is full "
  "of.")

note("Only sRGB and Rec.709 primaries are implemented — they are identical, so "
     "the conversion is exact. Wide-gamut primary conversion is not implemented, "
     "and the tool says so rather than doing something plausible-looking.", "NOTE")


# ---------------------------------------------------------------------------
# 13. Assets
# ---------------------------------------------------------------------------

section("Asset management")

p("Images are stored under their own SHA-256, which gives deduplication for "
  "free: a logo placed twenty times in a design is one file on disk and one "
  "transfer over the wire. Before sending, the plugin asks the bridge which "
  "hashes it already holds, so re-syncing a design full of photographs transfers "
  "almost nothing the second time.")

table(
    ["Behaviour", "Detail"],
    [
        ["Location", "~/Library/Application Support/FigmaFusionBridge/Assets"],
        ["Naming", "Content hash, with the original filename kept alongside"],
        ["Verification", "Bytes are re-hashed on arrival and rejected if they do not match"],
        ["Layout", "Two-level fan-out, so no single folder holds thousands of files"],
        ["Cleanup", "Settings → Asset cache shows the size and clears it"],
    ],
    [CONTENT_W * 0.22, CONTENT_W * 0.78],
)

p("Verification is not paranoia. A truncated upload stored under the expected "
  "hash would be cached as though it were correct, and then served to every "
  "future transfer.")


# ---------------------------------------------------------------------------
# 14. Fonts
# ---------------------------------------------------------------------------

section("Font management",
        "A missing font is always reported, never silently substituted.")

p("Swapping a typeface changes the design, and a designer who is not told will "
  "find out at the worst possible moment. Resolution works down a ladder of "
  "decreasing confidence, and the confidence is reported:")

table(
    ["Outcome", "What happens"],
    [
        ["Exact match", "Nothing to do."],
        ["Family found, weight missing",
         "The nearest weight is used, and the log says which and why."],
        ["Not installed",
         "The Text+ node keeps the original font name and warns. Install the font "
         "and it appears correctly — with no re-import."],
    ],
    [CONTENT_W * 0.28, CONTENT_W * 0.72],
)

note("Because the original name is preserved rather than replaced, fixing a "
     "missing font is a matter of installing it. You do not have to send the "
     "design again.", "TIP")


# ---------------------------------------------------------------------------
# 15. Workflows
# ---------------------------------------------------------------------------

section("Example workflows")

workflows = [
    ("UI motion",
     "Import a product screen, animate cards and buttons on their Anim transforms. "
     "The layout stays exactly on-brand because it was never redrawn."),
    ("YouTube lower thirds",
     "Build the design once, animate once, re-sync per episode when the text changes."),
    ("Vertical social",
     "A 1080×1920 Figma frame into a matching timeline. Pixel for pixel, no scaling guesswork."),
    ("Broadcast graphics",
     "Scoreboards and interface overlays stay crisp when the package is re-rendered at 4K, "
     "because native shapes are resolution independent."),
    ("Product video callouts",
     "Labels stay editable Text+, so a wording change is a retype rather than a re-export."),
    ("Animated typography",
     "Poster layouts arrive as real text with real tracking and leading."),
    ("Title sequences",
     "Style frames become a structured graph instead of a reference image to eyeball."),
    ("Explainer graphics",
     "Diagrams keep their hierarchy, so whole groups can be animated together."),
    ("Presentation builds",
     "Slide layouts import with z-order intact, ready for staggered reveals."),
    ("Client revisions",
     "The designer changes Figma; you press Receive; your animation is still there. "
     "This is the one the whole design is for."),
]
for i, (title, body) in enumerate(workflows, 1):
    story.append(KeepTogether([
        Paragraph(f"{i}. {title}", styles["H3"]),
        Paragraph(body, styles["Body"]),
    ]))


# ---------------------------------------------------------------------------
# 16. Limitations
# ---------------------------------------------------------------------------

section("Limitations",
        "Everything the bridge cannot do exactly. Nothing in this list fails silently.")

h2("Approximate — visually close, mathematically different")
bullets([
    "Per-corner radii: Fusion shapes take one radius; the largest is used.",
    "Angular and diamond gradients: Fusion's nearest equivalents differ at the edges.",
    "Shadow spread: no Fusion equivalent; softness is widened to compensate.",
    "Inside stroke on an ellipse: the true offset of an ellipse is not an ellipse. "
    "Warned only when thick enough to see.",
    "Mixed styles inside one text layer: the dominant style is used. The text stays editable.",
    "Justified text: Fusion's justify mode may break lines differently.",
])

h2("Experimental — built, but may differ in complex cases")
bullets([
    "Background blur. It needs the layers behind the object, so the graph has to "
    "branch and re-merge. Always warned.",
])

h2("Unsupported — reported, never faked")
bullets([
    "Non-separable blend modes: Hue, Saturation, Color, Luminosity. These need a "
    "colour-space subgraph that a Merge cannot express.",
    "Dashed strokes — drawn solid.",
    "Corner smoothing (squircle corners) — plain rounded corners are used.",
    "Video and pattern fills.",
    "Paragraph spacing and indent.",
])

h2("Known gaps")
bullets([
    "Auto Layout is imported as baked positions. The layout description already "
    "travels in the transfer, so live rebuilding is additive work.",
    "Per-character rich text uses the dominant style. Text+ exposes the input "
    "needed for true per-character styling.",
    "No automated visual regression suite yet. The conversion maths is "
    "unit-tested; pixel comparison against Figma renders is not.",
])


# ---------------------------------------------------------------------------
# 17. Troubleshooting
# ---------------------------------------------------------------------------

section("Troubleshooting",
        "Start with Connection Test in Resolve: Workspace → Scripts → Utility → "
        "Figma Fusion Bridge → Connection Test. It checks every link and names the "
        "broken one.")

table(
    ["Symptom", "Cause and fix"],
    [
        ["Plugin says “Bridge not running”",
         "The app is not open, or could not take a port. If 8787 is busy it tries "
         "8788–8791; the port in use is on the Status tab."],
        ["Pairing code refused",
         "Codes expire after ten minutes — press New code. The alphabet excludes "
         "0, O, 1, I and L, so a character you read as one of those is something else."],
        ["No Figma Fusion Bridge menu in Resolve",
         "Install the scripts, then <b>restart Resolve</b>. It scans its Scripts "
         "folder only at startup. This is the most common cause by a wide margin."],
        ["“not installed correctly”",
         "The scripts are present but the Python library is not. Use Setup → Reinstall."],
        ["“Nothing waiting to be received”",
         "Nothing has been sent since the bridge started. Send from Figma first."],
        ["“No open Fusion composition”",
         "Receive needs somewhere to put the graph. Select a clip and switch to the Fusion page."],
        ["A font came in wrong",
         "The log names it. Install the font — the Text+ kept the original name, so "
         "no re-import is needed."],
        ["A gradient became a flat colour",
         "The log contains GRADIENT_DEGRADED and the path to a .setting file with the "
         "full gradient. Drag that into the node graph."],
        ["Colours do not match",
         "The project is probably colour-managed. Switch Colour to “Use project colour”."],
        ["Re-sync duplicated everything",
         "The graph was pasted into a different composition than last time; manifests "
         "are per composition. Delete the duplicates and send once more."],
        ["Animation was overwritten",
         "Keyframes must live on the layer's *_Anim Transform. Nodes named *_Shape or "
         "*_Merge are rebuilt on every sync."],
        ["Live Sync stopped",
         "It debounces about a second after your last edit and pauses during a "
         "transfer. Toggle it off and on."],
    ],
    [CONTENT_W * 0.30, CONTENT_W * 0.70],
)


# ---------------------------------------------------------------------------
# 18. Architecture
# ---------------------------------------------------------------------------

section("Architecture")

code("""Figma plugin  (TypeScript)
   controller — reads the document
   UI iframe  — the only half with network access
        │  interchange JSON + assets by content hash
        ▼
macOS bridge  (Swift)
   BridgeCore library + menu-bar app
   127.0.0.1 only · pairing · queue · asset cache
        │  HTTP long poll — stdlib only
        ▼
Resolve scripts  (Python)
   fetch → validate → build → apply
   FusionGraphBuilder: JSON → Fusion ASCII, pure
        ▼
   Fusion node graph""")

h2("Why the builder emits text")
p("Creating nodes one at a time costs an inter-process round trip per input — "
  "roughly two thousand for a 150-layer frame — and cannot express structured "
  "values like a gradient from Python. Generating the whole composition as "
  "Fusion's own ASCII format is one hand-off regardless of size, expresses every "
  "value exactly, and makes the builder a pure function.")

p("That last point is the one that matters most. Because the builder is pure, "
  "every conversion rule in the product — coordinates, gradients, stroke "
  "geometry, colour, blend modes — is covered by tests that run without Figma or "
  "Resolve present.")

h2("Verified, not assumed")
p("Every Fusion node id and input name was read out of composition files shipped "
  "by Blackmagic Design, or out of the Fusion libraries themselves. This caught "
  "several things that a from-memory implementation would have got wrong: the "
  "drop-shadow node is <font face='Courier'>Shadow</font>, not "
  "<font face='Courier'>DropShadow</font>; the alignment inputs are "
  "<font face='Courier'>HorizontalJustificationNew</font>, not the un-suffixed "
  "legacy names; and Fusion's blend-mode identifiers are inconsistently spaced — "
  "<font face='Courier'>\"Color Burn\"</font> with a space, "
  "<font face='Courier'>\"LinearBurn\"</font> without.")

note("An unrecognised identifier is silently ignored by Fusion. A wrong guess "
     "therefore produces no error anywhere — just a wrong picture. That is why "
     "verification is a rule in this project rather than a preference.", "NOTE")


# ---------------------------------------------------------------------------
# 19. Security
# ---------------------------------------------------------------------------

section("Security and privacy",
        "Your designs never leave this Mac.")

table(
    ["Measure", "How"],
    [
        ["Loopback only",
         "The listeners are pinned to 127.0.0.1 and ::1. There is no code path "
         "that binds another interface and no setting that exposes one. Both "
         "loopback families are bound because Figma's manifest accepts only host "
         "names, and localhost resolves to both."],
        ["Pairing required",
         "Any web page you have open can reach a loopback port, so the port is not "
         "a permission. A six-character code, shown in the app, is exchanged once "
         "for a token. Every endpoint that does anything requires it."],
        ["Expiring codes",
         "Ten minutes, and regenerated on every launch, so a code seen over a "
         "shoulder is not useful later."],
        ["Constant-time comparison",
         "On both the code and the token — the code is short enough that timing "
         "would narrow the search."],
        ["Token file is 0600",
         "It is a credential, and the Resolve scripts read it as you."],
        ["Content verification",
         "Every uploaded asset is re-hashed and rejected if it does not match."],
        ["Schema validation",
         "Every document is checked before it reaches the builder."],
        ["No cloud",
         "There is no remote component in the transfer path. No account, no telemetry."],
    ],
    [CONTENT_W * 0.24, CONTENT_W * 0.76],
)


# ---------------------------------------------------------------------------
# 20. FAQ
# ---------------------------------------------------------------------------

section("Frequently asked questions")

faq = [
    ("Does it work with the free edition of DaVinci Resolve?",
     "That is what the architecture is designed for. Resolve pulls work from the "
     "bridge using a script you launch from its own menu, rather than being driven "
     "from outside — which is the part that has historically been Studio-only."),
    ("Does anything leave my computer?",
     "No. The bridge listens on 127.0.0.1 and there is no remote component in the "
     "transfer path."),
    ("Can I use Figma in the browser rather than the desktop app?",
     "Yes. The plugin runs the same either way, and the bridge is on your Mac in "
     "both cases."),
    ("What happens if I rename a layer in Figma?",
     "Nothing breaks. Identity comes from the layer id, not the name."),
    ("What happens if I rename a node in Fusion?",
     "Also nothing. Identity is stored on the node itself, not read from its name."),
    ("Will re-syncing destroy my animation?",
     "Not if your keyframes are on the *_Anim transforms, which is where the "
     "importer puts a node for exactly this purpose."),
    ("Why is my text white?",
     "Gradient and image fills on text are not reproduced. White is used so it is "
     "visible and easy to re-colour, and the log says so."),
    ("Why did a vector layer come in as an image?",
     "Custom paths and boolean operations are exported as SVG rather than rebuilt "
     "as Fusion splines. They stay resolution independent."),
    ("Can I add Sketch or Illustrator support?",
     "The interchange format is deliberately source-agnostic — it mentions Figma "
     "once, as a value. A new producer is a sibling of the Figma extractor, and the "
     "graph builder does not change."),
    ("Do I need Xcode to build this?",
     "No. The Command Line Tools are enough. The app avoids macro-based property "
     "wrappers and the Swift tests avoid XCTest, both of which ship only with Xcode."),
]
for question, answer in faq:
    story.append(KeepTogether([
        Paragraph(question, styles["H3"]),
        Paragraph(answer, styles["Body"]),
    ]))


# ---------------------------------------------------------------------------
# 21. Shortcuts
# ---------------------------------------------------------------------------

section("Keyboard shortcuts")

p("The plugin follows Figma's own conventions. The bridge deliberately registers "
  "no global shortcuts: a background utility should not take a key combination "
  "away from the applications you are working in.")

table(
    ["Where", "Key", "Action"],
    [
        ["Figma plugin", "Enter", "Confirm the pairing code"],
        ["Figma plugin", "Esc", "Close the plugin"],
        ["Resolve", "—", "Assign Receive a shortcut in Resolve's Keyboard Customisation"],
        ["Bridge", "—", "None by default, by design"],
    ],
    [CONTENT_W * 0.24, CONTENT_W * 0.18, CONTENT_W * 0.58],
)


# ---------------------------------------------------------------------------
# 22. Changelog
# ---------------------------------------------------------------------------

section("Changelog")

h2("0.1.0 — first working release")
p("Interchange format 1.0.0. Figma plugin with full selection extraction. "
  "Native arm64 menu-bar bridge with loopback-only HTTP, pairing and a "
  "content-addressed asset cache. Fusion graph builder producing native shapes, "
  "editable Text+, native gradients, geometric stroke alignment, drop shadow, "
  "layer blur and constructed inner shadow, with hierarchy and z-order preserved. "
  "Resolve scripts for Receive, Receive Into Current Composition, Pull Current "
  "Figma Selection and Connection Test. 288 tests requiring neither Figma, "
  "Resolve nor Xcode.")

h2("Corrections made during development")
bullets([
    "Font enumeration moved from system_profiler — which returns an empty "
    "document on macOS 27 and cost 9.3 seconds — to CoreText. Import time fell "
    "from 9577 ms to 4 ms.",
    "Rotation is applied about a layer's real centre, found by pushing the local "
    "midpoint through its absolute transform. Design tools rotate about the "
    "top-left corner, so adding half the width is correct only for unrotated layers.",
    "Server startup moved out of a view's task: as a menu-bar app there is no "
    "window at launch, so the bridge never began listening until someone opened "
    "the dashboard.",
])

story.append(Spacer(1, 14))
story.append(HRule(CONTENT_W))
story.append(Paragraph(
    f"{PRODUCT} · Version {VERSION} · MIT licensed.<br/>"
    "Independent integration using the Figma Plugin API and "
    "the DaVinci Resolve Scripting SDK.",
    styles["Caption"]))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
    out = os.path.normpath(os.path.join(
        out_dir, f"Figma-Fusion-Bridge-Manual-v{VERSION}.pdf"))
    doc = Manual(out)
    # Two passes: the first collects page numbers, the second renders the
    # contents with them. multiBuild does that.
    doc.multiBuild(story)
    size = os.path.getsize(out)
    print(f"Built {out} ({size / 1024:.0f} KB, {doc.page - 1} pages)")


if __name__ == "__main__":
    main()
