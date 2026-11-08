"""The panel demo's packages are the panel's own, at the panel's versions.

``demo/`` installs its own ``node_modules`` from ``demo/package.json``. It
names each package of ``hub/frontend/package.json`` but the lint and format
tools, in the same section with the same version, and both lock files hold
each of its packages at one version.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PANEL_DIR = REPO_ROOT / "hub" / "frontend"
DEMO_DIR = REPO_ROOT / "demo"
MANIFEST_SECTIONS = ("dependencies", "devDependencies")
# The panel's packages the demo leaves out: its lint and format tools.
DEMO_LEFT_OUT_PACKAGES = {
    "@eslint/js",
    "eslint",
    "eslint-config-prettier",
    "eslint-plugin-react-hooks",
    "eslint-plugin-react-refresh",
    "globals",
    "prettier",
    "typescript-eslint",
}


def manifest(directory: Path) -> dict:
    """The packages a ``package.json`` names, by section."""
    data = json.loads((directory / "package.json").read_text(encoding="utf-8"))
    return {section: data.get(section, {}) for section in MANIFEST_SECTIONS}


def locked_versions(directory: Path) -> dict:
    """Each installed path of a ``package-lock.json`` and its version."""
    data = json.loads((directory / "package-lock.json").read_text(encoding="utf-8"))
    return {
        path: entry.get("version")
        for path, entry in data["packages"].items()
        if path.startswith("node_modules/")
    }


def test_the_demo_names_each_panel_package_it_needs_at_the_panel_version():
    panel = manifest(PANEL_DIR)
    needed = {
        section: {
            name: version
            for name, version in packages.items()
            if name not in DEMO_LEFT_OUT_PACKAGES
        }
        for section, packages in panel.items()
    }

    assert manifest(DEMO_DIR) == needed


def test_the_demo_lock_holds_each_package_at_the_panel_lock_version():
    panel = locked_versions(PANEL_DIR)
    demo = locked_versions(DEMO_DIR)
    differing = {
        path: (panel.get(path), version)
        for path, version in demo.items()
        if panel.get(path) != version
    }

    assert demo
    assert differing == {}
