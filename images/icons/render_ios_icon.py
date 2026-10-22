"""Render the iOS app's icon from the Neutrino mark.

The icon is the mark on the panel's background, ``#0a0e14``, over the whole
square: opaque, with square corners, which iOS rounds itself.

Run from the repository root with Pillow installed; it writes
``neutrino_ios.png`` at the one edge iOS takes.
"""

from pathlib import Path

from PIL import Image

ICONS_DIR = Path(__file__).resolve().parent
SOURCE = ICONS_DIR / "neutrino.png"
TARGET = ICONS_DIR / "neutrino_ios.png"
EDGE = 1024
# The panel's background, the colour the mark's own square is drawn in.
BACKGROUND = (10, 14, 20)


def render() -> Image.Image:
    """The iOS icon: the mark on an opaque square of the panel's background."""
    mark = Image.open(SOURCE).convert("RGBA")
    canvas = Image.new("RGBA", mark.size, BACKGROUND + (255,))
    canvas.alpha_composite(mark)
    return canvas.convert("RGB").resize((EDGE, EDGE), Image.LANCZOS)


def main() -> None:
    """Write the icon."""
    render().save(TARGET)


if __name__ == "__main__":
    main()
