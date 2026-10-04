"""The edition table: the one way the client reaches NetBird.

Every Python file of the client and its packaging is read, and an import of
NetBird's own files from anywhere else than those files and the table
fails here. Every hook the table names lives in NetBird's own files, and
every path of NetBird's own files is one the mainland tree leaves out.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

from neutrino_client import edition

CLIENT_ROOT = Path(edition.__file__).resolve().parents[1]
REPO_ROOT = CLIENT_ROOT.parents[1]
# NetBird's own files in the client, as module names: the package's own,
# and the packaging part that sits on the path by its own name.
FEATURE_MODULES = {
    "netbird": ("neutrino_client.netbird", "netbird_payload"),
}
# Where each own module of a feature sits in the repository.
FEATURE_MODULE_PATHS = {
    "neutrino_client.netbird": "client/desktop/neutrino_client/netbird",
    "netbird_payload": "client/desktop/packaging/netbird_payload.py",
}
# The files read: the package, its packaging and its tests, and the build
# scripts that lay the packages out.
SOURCE_DIRS = ("neutrino_client", "packaging", "tests")
BUILD_SCRIPTS = (
    "packaging/build/build_client_windows.py",
    "packaging/build/build_client_macos.py",
    "packaging/build/build_client_desktop.py",
)


def module_name(path: Path) -> str:
    """The dotted name one file of the client is imported by."""
    if path.parent == CLIENT_ROOT / "packaging":
        return path.stem
    relative = path.relative_to(CLIENT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def feature_of(name: str) -> "str | None":
    """The feature whose own files hold a module, None for the rest."""
    for feature, modules in FEATURE_MODULES.items():
        if any(name == module or name.startswith(module + ".") for module in modules):
            return feature
    if name == "tests.netbird" or name.startswith("tests.netbird."):
        return "netbird"
    if name == "tests.packaging.test_netbird_payload":
        return "netbird"
    return None


def imported_names(path: Path) -> list:
    """Every module one file imports, by its dotted name."""
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def every_file() -> list:
    """Every Python file the rule covers, with the module name it has."""
    files = []
    for directory in SOURCE_DIRS:
        for path in sorted((CLIENT_ROOT / directory).rglob("*.py")):
            files.append((path, module_name(path)))
    for relative in BUILD_SCRIPTS:
        path = REPO_ROOT / relative
        if path.is_file():
            files.append((path, path.stem))
    return files


def test_no_file_outside_netbird_imports_it():
    """Deleting NetBird's files breaks nothing that stays."""
    found = []
    table = Path(edition.__file__).resolve()
    for path, name in every_file():
        if path == table:
            continue
        owner = feature_of(name)
        for imported in imported_names(path):
            target = feature_of(imported)
            if target is not None and target != owner:
                found.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
    assert found == []


def test_every_hook_lives_in_its_features_own_files():
    for point, entries in edition.EDITION_HOOKS.items():
        for feature, target in entries:
            module, _, attribute = target.partition(":")
            assert feature_of(module) == feature, (point, target)
            if edition.has_feature(feature):
                assert hasattr(importlib.import_module(module), attribute), target


def left_out_paths() -> tuple:
    """The client's paths the mainland tree leaves out."""
    sys.path.insert(0, str(REPO_ROOT / "packaging"))
    try:
        from shared.constants import PACKAGING_CN_LEFT_OUT_PATHS
    finally:
        sys.path.remove(str(REPO_ROOT / "packaging"))
    return tuple(
        path
        for path in PACKAGING_CN_LEFT_OUT_PATHS
        if path.startswith("client/desktop/")
    )


def test_the_mainland_tree_leaves_out_every_own_module():
    for modules in FEATURE_MODULES.values():
        for module in modules:
            assert FEATURE_MODULE_PATHS[module] in left_out_paths()


def test_every_left_out_python_file_is_a_features_own():
    for relative in left_out_paths():
        path = REPO_ROOT / relative
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file in files:
            if file.suffix == ".py":
                assert feature_of(module_name(file)) is not None, relative


@pytest.mark.feature("netbird")
def test_a_full_tree_carries_every_left_out_path():
    assert edition.has_feature("netbird") is True
    for relative in left_out_paths():
        assert (REPO_ROOT / relative).exists(), relative


def test_an_absent_feature_gives_no_point_anything(monkeypatch):
    monkeypatch.setattr(edition, "has_feature", lambda name: False)

    for point in edition.EDITION_HOOKS:
        assert edition.hooks(point) == ()


def test_a_package_that_does_not_import_is_absent(monkeypatch):
    monkeypatch.setitem(
        edition.EDITION_FEATURE_PACKAGES, "netbird", "neutrino_client.nothing_here"
    )
    monkeypatch.setattr(edition, "_present", {})

    assert edition.has_feature("netbird") is False
    assert edition.hooks("overlay_drivers") == ()


def test_an_unknown_point_or_feature_is_refused():
    with pytest.raises(KeyError):
        edition.hooks("no_such_point")
    with pytest.raises(KeyError):
        edition.has_feature("proxy")


def test_a_checkout_reads_its_edition_from_the_root_file():
    named = (REPO_ROOT / edition.EDITION_FILE_NAME).read_text(encoding="utf-8")

    assert named.strip() in edition.EDITIONS
    assert edition._checkout_edition() == named.strip()


def test_a_missing_or_unknown_root_file_reads_as_intl(monkeypatch, tmp_path):
    fake = tmp_path / "client" / "desktop" / "neutrino_client" / "edition.py"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(edition, "__file__", str(fake))

    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("elsewhere\n", encoding="utf-8")
    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("cn\n", encoding="utf-8")
    assert edition._checkout_edition() == "cn"


def test_a_built_package_reads_the_stamp(monkeypatch):
    """The stamp a build writes outranks the root file."""
    import types

    stamp = types.ModuleType("neutrino_client._version")
    stamp.EDITION = "cn"
    monkeypatch.setitem(sys.modules, "neutrino_client._version", stamp)
    try:
        assert importlib.reload(edition).EDITION == "cn"
    finally:
        monkeypatch.delitem(sys.modules, "neutrino_client._version")
        importlib.reload(edition)
