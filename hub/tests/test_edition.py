"""The edition table: the one way the hub reaches a left-out feature.

Every Python file of the hub is read, and an import of the proxy's or
NetBird's own files from anywhere else than that feature's files and the
table fails here. Every hook the table names resolves in a tree that carries
its feature, lives in that feature's own files, and is left out when the
feature is absent.
"""

import ast
import importlib
import re
from pathlib import Path

import pytest

from neutrino_hub import edition

PACKAGE_ROOT = Path(edition.__file__).resolve().parent
# Each feature's own files in the hub, as module names: a package, or one
# module. The architecture page's table says the same.
FEATURE_MODULES = {
    "proxy": (
        "neutrino_hub.modules.xray",
        "neutrino_hub.modules.tun",
        "neutrino_hub.web.routers.hub.proxy",
        "neutrino_hub.web.routers.hub.proxy_node",
    ),
    "netbird": (
        "neutrino_hub.modules.netbird",
        "neutrino_hub.web.routers.hub.overlay_netbird",
    ),
}


def module_name(path: Path) -> str:
    """The dotted name of one file of the hub."""
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def feature_of(name: str) -> "str | None":
    """The feature whose own files hold a module, None for the rest."""
    for feature, modules in FEATURE_MODULES.items():
        if any(name == module or name.startswith(module + ".") for module in modules):
            return feature
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


def test_no_file_outside_a_feature_imports_it():
    """Deleting a feature's files breaks nothing that stays: nothing else
    imports them, the other left-out feature included."""
    found = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        owner = feature_of(module_name(path))
        if path == Path(edition.__file__).resolve():
            continue
        for name in imported_names(path):
            target = feature_of(name)
            if target is not None and target != owner:
                found.append(f"{path.relative_to(PACKAGE_ROOT)} imports {name}")
    assert found == []


def test_every_hook_lives_in_its_features_own_files():
    for point, entries in edition.EDITION_HOOKS.items():
        for feature, target in entries:
            module, _, attribute = target.partition(":")
            assert feature_of(module) == feature, (point, target)
            if edition.has_feature(feature):
                assert hasattr(importlib.import_module(module), attribute), target


def test_the_table_names_each_feature_by_one_of_its_packages():
    for feature, package in edition.EDITION_FEATURE_PACKAGES.items():
        assert feature_of(package) == feature


@pytest.mark.feature("proxy")
@pytest.mark.feature("netbird")
def test_a_full_tree_carries_both_features():
    assert edition.has_feature("proxy") is True
    assert edition.has_feature("netbird") is True


def test_an_absent_feature_gives_no_point_anything(monkeypatch):
    monkeypatch.setattr(edition, "has_feature", lambda name: False)

    for point in edition.EDITION_HOOKS:
        assert edition.hooks(point) == ()
        assert edition.hook(point) is None


@pytest.mark.feature("netbird")
def test_a_package_that_does_not_import_is_absent(monkeypatch):
    monkeypatch.setitem(
        edition.EDITION_FEATURE_PACKAGES, "proxy", "neutrino_hub.modules.nothing_here"
    )
    monkeypatch.setattr(edition, "_present", {})

    assert edition.has_feature("proxy") is False
    assert edition.hooks("api_routers") == (
        importlib.import_module("neutrino_hub.web.routers.hub.overlay_netbird").router,
    )


def test_an_unknown_point_or_feature_is_refused():
    with pytest.raises(KeyError):
        edition.hooks("no_such_point")
    with pytest.raises(KeyError):
        edition.has_feature("no_such_feature")


def test_a_checkout_reads_its_edition_from_the_root_file():
    root_file = PACKAGE_ROOT.parent.parent / edition.EDITION_FILE_NAME

    assert root_file.read_text(encoding="utf-8").strip() in edition.EDITIONS
    assert edition._checkout_edition() == root_file.read_text(encoding="utf-8").strip()


def test_a_missing_or_unknown_root_file_reads_as_intl(monkeypatch, tmp_path):
    fake = tmp_path / "hub" / "neutrino_hub" / "edition.py"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(edition, "__file__", str(fake))

    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("elsewhere\n", encoding="utf-8")
    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("cn\n", encoding="utf-8")
    assert edition._checkout_edition() == "cn"


def test_a_built_package_reads_the_stamp(monkeypatch):
    """The stamp a build writes outranks the root file."""
    import sys
    import types

    stamp = types.ModuleType("neutrino_hub._version")
    stamp.EDITION = "cn"
    monkeypatch.setitem(sys.modules, "neutrino_hub._version", stamp)
    try:
        reloaded = importlib.reload(edition)
        assert reloaded.EDITION == "cn"
    finally:
        monkeypatch.delitem(sys.modules, "neutrino_hub._version")
        importlib.reload(edition)


# Core strings that name a left-out feature and act on nothing of it, each
# with the reason it stays.
NAMED_STRINGS_ALLOWED = {
    ("modules/overlay/constants.py", "netbird"): (
        "the key a stored overlay row names; an absent engine's rows are "
        "dropped when the file is read"
    ),
    ("modules/router/constants.py", "side_gateway"): (
        "the name a stored mode carries; the modes offered come from the table"
    ),
    ("modules/router/resolver.py", "# Generated by NetBird"): (
        "recognises a resolver file a NetBird on the machine wrote"
    ),
    ("modules/router/resolver.py", "/etc/resolv.conf.original.netbird"): (
        "where such a NetBird keeps the file it replaced"
    ),
    ("platforms/constants.py", "netbird.sock"): (
        "a platform fact read only by NetBird's own files"
    ),
    ("web/constants.py", "xray"): (
        "the DNS log's word for a forward to the proxy's inbound, which only "
        "the proxy's hook makes true"
    ),
    ("web/routers/hub/network.py", "access_point_cannot_be_side_gateway"): (
        "a refusal's code"
    ),
}
FEATURE_WORDS = re.compile(r"xray|netbird|tun2socks|geodata|side_gateway", re.I)


def named_strings(path: Path) -> list:
    """Every string in one file naming a left-out feature, docstrings aside."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and FEATURE_WORDS.search(node.value)
    ]


def test_no_core_string_names_a_left_out_feature():
    """A unit, a stop order, an option or a step that names the proxy or
    NetBird outside their own files is one the mainland tree acts on and
    does not carry. Comments and docstrings are free to name them."""
    found = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path == Path(edition.__file__).resolve():
            continue
        if feature_of(module_name(path)) is not None:
            continue
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        for value in named_strings(path):
            if (relative, value) not in NAMED_STRINGS_ALLOWED:
                found.append(f"{relative}: {value!r}")
    assert found == []


def test_no_docstring_printed_as_help_names_a_left_out_feature():
    """A command whose ``--help`` prints its whole docstring shows it to the
    person, so it names neither the proxy nor NetBird."""
    shown = []
    for path in sorted((PACKAGE_ROOT / "cli").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "description=__doc__)" not in source:
            continue
        shown.append(path.name)
        doc = ast.get_docstring(ast.parse(source)) or ""
        assert not re.search(
            r"proxy|xray|netbird|tun2socks|geodata", doc, re.I
        ), path.name
    assert shown
