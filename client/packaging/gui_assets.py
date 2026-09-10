"""Stage the GUI page and icon into a built client package tree.

The page's source of truth is ``client/frontend/``; the one icon source is
``images/icons/`` at the repository root. Every client package build copies
both into the package's ``data/gui/``, which a checkout does not carry.

Not pure: copies files.
"""

import shutil
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = CLIENT_ROOT / "frontend"
ICONS_DIR = CLIENT_ROOT.parent / "images" / "icons"


def stage_gui(package_dir: Path) -> None:
    """Copy the page files and the window icon into ``data/gui``.

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
    shutil.copyfile(ICONS_DIR / "neutrino_256.png", gui_dir / "neutrino_client.png")
