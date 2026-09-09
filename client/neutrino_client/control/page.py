"""The client's GUI page, loaded from the frontend files the package ships.

The page is plain HTML, CSS and JavaScript under ``client/frontend/``, copied
into ``neutrino_client/data/gui/`` by the packaging builds; a checkout with
no built copy reads the source directory directly. The page renders two
sections, Status and Services, and its requests ride the in-process channel
over a message bridge.

The page redraws only when the state payload actually changed, and never
while the person holds a text selection, a focused form field, or an open
dialog.
"""

import pathlib

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
GUI_DATA_DIR = _PACKAGE_DIR / "data" / "gui"
GUI_SOURCE_DIR = _PACKAGE_DIR.parent / "frontend"

GUI_STYLE_TAG = '<link rel="stylesheet" href="style.css">'
GUI_SCRIPT_TAG = '<script src="app.js"></script>'


def gui_dir() -> pathlib.Path:
    """The directory the page's files load from.

    Returns:
        The packaged ``data/gui`` directory when it holds the page, the
        ``client/frontend`` source directory otherwise.

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


def control_page_html() -> str:
    """The whole page as one document, for a shell's ``load_html``.

    Returns:
        ``index.html`` with the stylesheet and the script inlined.

    Raises:
        ValueError: When ``index.html`` lacks the tags the assets replace.
    """
    document = gui_asset("index.html")
    for tag, opening, content, closing in (
        (GUI_STYLE_TAG, "<style>", gui_asset("style.css"), "</style>"),
        (GUI_SCRIPT_TAG, "<script>", gui_asset("app.js"), "</script>"),
    ):
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
    for path in (
        GUI_DATA_DIR / "neutrino_client.png",
        _PACKAGE_DIR.parent.parent / "images" / "icons" / "neutrino_256.png",
    ):
        if path.is_file():
            return str(path)
    return ""
