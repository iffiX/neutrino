"""Stage the GUI page and icon into a built client package tree.

The page's source of truth is ``client/desktop/frontend/``; the one icon
source is ``images/icons/`` at the repository root. Every client package build
copies both into the package's ``data/gui/``, which a checkout does not carry.
The word catalogs go with them, under ``data/gui/locales/``, where the page's
loader and the resident both read them, and the vendored terminal library
under ``data/gui/vendor/``.

Not pure: copies files.
"""

import shutil
from pathlib import Path

from shared import icons

CLIENT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = CLIENT_ROOT / "frontend"
LOCALES_DIR = FRONTEND_DIR / "locales"
VENDOR_DIR = FRONTEND_DIR / "vendor"
# The window icon's edge, and the launcher's edges in the icon theme.
WINDOW_ICON_EDGE = 256
LAUNCHER_ICON_EDGES = (16, 32, 48, 64, 128, 256)


def stage_gui(package_dir: Path) -> None:
    """Copy the page, its word catalogs and the window icon into ``data/gui``.

    Args:
        package_dir: The copied ``neutrino_client`` package in a build tree.

    Raises:
        FileNotFoundError: When the frontend or the icons are not beside
            this script's tree.
    """
    gui_dir = package_dir / "data" / "gui"
    gui_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(FRONTEND_DIR.iterdir()):
        if source.is_file():
            shutil.copyfile(source, gui_dir / source.name)
    locales_dir = gui_dir / "locales"
    locales_dir.mkdir(exist_ok=True)
    for source in sorted(LOCALES_DIR.glob("*.json")):
        shutil.copyfile(source, locales_dir / source.name)
    vendor_dir = gui_dir / "vendor"
    vendor_dir.mkdir(exist_ok=True)
    for source in sorted(VENDOR_DIR.iterdir()):
        if source.is_file():
            shutil.copyfile(source, vendor_dir / source.name)
    icons.write_png(gui_dir / "neutrino_client.png", WINDOW_ICON_EDGE)
    # Windows loads a window and tray icon from an .ico and from nothing
    # else; a .png there leaves the stock grey application icon.
    icons.write_ico(gui_dir / "neutrino_client.ico")


def stage_launcher_icons(tree: Path, desktop_name: str) -> None:
    """Write the launcher's icons into a Linux package's icon theme.

    Args:
        tree: The directory standing in for the filesystem root.
        desktop_name: The icon's name, the launcher's desktop name.

    Raises:
        SystemExit: When an icon source is missing or is not a PNG of its size.
    """
    for edge in LAUNCHER_ICON_EDGES:
        target = icons.write_png(
            tree / f"usr/share/icons/hicolor/{edge}x{edge}/apps/{desktop_name}.png",
            edge,
        )
        target.chmod(0o644)
