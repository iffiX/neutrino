"""Render the hub's application icon from the Neutrino mark.

The hub's entry looks like the panel's brand box: the mark on its dark
square, the square's edge drawn in the panel's accent, and a soft glow of
the same accent around it. The client's entry is the plain mark.

Run from the repository root with Pillow installed; it writes
``neutrino_hub.png`` and one file per edge packaging asks for.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ICONS_DIR = Path(__file__).resolve().parent
SOURCE = ICONS_DIR / "neutrino.png"
TARGET_NAME = "neutrino_hub"
EDGES = (16, 32, 48, 64, 128, 256, 512)
# The panel's dark accent, #22d3ee.
ACCENT = (34, 211, 238)
# How much of the canvas the box takes; the rest is the glow's room.
BOX_SHARE = 0.84
# The box's corner, border and glow, as shares of the box's edge, matching
# the panel's 6 px corner, 1 px border and 20 px glow on a 28 px box.
CORNER_SHARE = 0.21
BORDER_SHARE = 0.036
GLOW_SHARE = 0.5
GLOW_ALPHA = 150


def render(edge: int) -> Image.Image:
    """The hub icon at one edge."""
    scale = 4
    size = edge * scale
    box = int(size * BOX_SHARE)
    offset = (size - box) // 2
    corner = int(box * CORNER_SHARE)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        (offset, offset, offset + box, offset + box),
        radius=corner,
        fill=ACCENT + (GLOW_ALPHA,),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(box * GLOW_SHARE * 0.18))
    canvas.alpha_composite(glow)

    mark = Image.open(SOURCE).convert("RGBA").resize((box, box), Image.LANCZOS)
    mask = Image.new("L", (box, box), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, box - 1, box - 1), radius=corner, fill=255)
    mark.putalpha(mask)
    canvas.alpha_composite(mark, (offset, offset))

    border = max(scale, int(box * BORDER_SHARE))
    ImageDraw.Draw(canvas).rounded_rectangle(
        (offset, offset, offset + box - 1, offset + box - 1),
        radius=corner,
        outline=ACCENT + (255,),
        width=border,
    )
    return canvas.resize((edge, edge), Image.LANCZOS)


def main() -> None:
    """Write the source-size icon and every packaged edge."""
    render(1254).save(ICONS_DIR / f"{TARGET_NAME}.png")
    for edge in EDGES:
        render(edge).save(ICONS_DIR / f"{TARGET_NAME}_{edge}.png")


if __name__ == "__main__":
    main()
