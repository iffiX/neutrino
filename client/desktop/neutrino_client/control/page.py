"""The client's GUI page, loaded from the frontend files the package ships.

The page is plain HTML, CSS and JavaScript under ``client/desktop/frontend/``,
copied into ``neutrino_client/data/gui/`` by the packaging builds; a checkout
with no built copy reads the source directory directly. The page's requests
ride the in-process channel over a message bridge. The document carries both
word catalogs inlined, the way the stylesheets and the scripts are, xterm.js
from ``vendor/`` among them, so the page loads nothing on its own; the
terminal's font comes over the same bridge, one piece per request.

The page redraws only when the state payload actually changed, and never
while the person holds a text selection, a focused form field, or an open
dialog.
"""

import base64
import json
import os
import pathlib

from neutrino_client import words

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
GUI_DATA_DIR = _PACKAGE_DIR / "data" / "gui"
GUI_SOURCE_DIR = _PACKAGE_DIR.parent / "frontend"

GUI_STYLE_TAG = '<link rel="stylesheet" href="style.css">'
GUI_SCRIPT_TAG = '<script src="app.js"></script>'
GUI_WORDS_OPENING = '<script id="words" type="application/json">'
GUI_WORDS_TAG = GUI_WORDS_OPENING + "{}</script>"
# The terminal's library, its fit addon and its stylesheet, as the page
# names them under ``vendor/``.
GUI_VENDOR_STYLES = ("vendor/xterm.css",)
GUI_VENDOR_SCRIPTS = ("vendor/xterm.js", "vendor/addon-fit.js")
# The terminal's font, MesloLGS NF, by the name the page asks for each face.
# The faces are read in pieces over the bridge rather than inlined: WebView2
# takes a document of at most 2 MiB.
GUI_TERMINAL_FONTS = {
    "regular": "vendor/MesloLGSNF-Regular.ttf",
    "bold": "vendor/MesloLGSNF-Bold.ttf",
}
GUI_FONT_CHUNK_BYTES = 512 * 1024


def gui_dir() -> pathlib.Path:
    """The directory the page's files load from.

    Returns:
        The packaged ``data/gui`` directory when it holds the page, the
        ``client/desktop/frontend`` source directory otherwise.

    Raises:
        FileNotFoundError: When neither directory holds the page.
    """
    for directory in (GUI_DATA_DIR, GUI_SOURCE_DIR):
        if (directory / "index.html").is_file():
            return directory
    raise FileNotFoundError("the client package carries no GUI page")


def gui_asset(name: str) -> str:
    """One of the page's files, as text.

    Args:
        name: The file name, e.g. ``app.js``.

    Returns:
        The file's content.
    """
    return (gui_dir() / name).read_text(encoding="utf-8")


def terminal_font_piece(name: str, offset: int) -> dict:
    """One piece of one face of the terminal's font.

    Args:
        name: The face, a key of ``GUI_TERMINAL_FONTS``.
        offset: Where in the file the piece starts.

    Returns:
        ``{"data", "offset", "size"}``: at most ``GUI_FONT_CHUNK_BYTES`` of
        the file as base64, where they start, and the file's whole size.

    Raises:
        KeyError: When ``name`` names no face.
        FileNotFoundError: When the face is not on this machine.
    """
    path = gui_dir() / GUI_TERMINAL_FONTS[name]
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        start = min(max(int(offset), 0), size)
        stream.seek(start)
        data = stream.read(GUI_FONT_CHUNK_BYTES)
    return {
        "data": base64.b64encode(data).decode("ascii"),
        "offset": start,
        "size": size,
    }


def control_page_html() -> str:
    """The whole page as one document, for a shell's ``load_html``.

    Returns:
        ``index.html`` with the stylesheets, the word catalogs and the
        scripts inlined, the terminal's library among them.

    Raises:
        FileNotFoundError: When the word catalogs or a vendored file are not
            on this machine.
        ValueError: When ``index.html`` lacks the tags the assets replace.
    """
    document = gui_asset("index.html")
    vendored = [
        (
            f'<link rel="stylesheet" href="{name}">',
            "<style>",
            gui_asset(name),
            "</style>",
        )
        for name in GUI_VENDOR_STYLES
    ] + [
        (f'<script src="{name}"></script>', "<script>", gui_asset(name), "</script>")
        for name in GUI_VENDOR_SCRIPTS
    ]
    for tag, opening, content, closing in vendored + [
        (GUI_STYLE_TAG, "<style>", gui_asset("style.css"), "</style>"),
        (
            GUI_WORDS_TAG,
            GUI_WORDS_OPENING,
            json.dumps(words.catalogs(), ensure_ascii=False),
            "</script>",
        ),
        (GUI_SCRIPT_TAG, "<script>", gui_asset("app.js"), "</script>"),
    ]:
        if tag not in document:
            raise ValueError(f"index.html does not carry {tag}")
        document = document.replace(tag, f"{opening}\n{content}{closing}")
    return document


def window_icon_path() -> str:
    """The window icon's file path, empty when no icon is on the machine.

    Returns:
        The packaged icon when the build copied one in, the repository's
        source icon in a checkout, empty otherwise.
    """
    names = ["neutrino_client.png"]
    if os.name == "nt":
        # Windows takes a window and tray icon from an .ico and from nothing
        # else, so that one comes first where it exists.
        names.insert(0, "neutrino_client.ico")
    candidates = [GUI_DATA_DIR / name for name in names]
    candidates.append(_PACKAGE_DIR.parents[2] / "images" / "icons" / "neutrino_256.png")
    for path in candidates:
        if path.is_file():
            return str(path)
    return ""
