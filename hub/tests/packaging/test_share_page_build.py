"""The App share page's tree as ``build_share_page.py`` writes it.

The shell page is the tree's root ``index.html``, and the three scripts are
under ``__neutrino/``. Each script's address in the built page carries ``?v=`` and the first 10 hex
characters of the script's content's sha256. The source names each script
with no fingerprint and runs unbuilt.
"""

import hashlib
import json
import re
import shutil

import pytest

import build_share_page

SOURCE_DIR = build_share_page.SHARE_PAGE_DIR
# The scripts under __neutrino/.
SCRIPTS = ("shell.js", "sw.js", "shim.js")
# Each script and the file that names its address.
SCRIPT_NAMERS = (
    ("shim.js", "sw.js"),
    ("sw.js", "shell.js"),
    ("shell.js", "index.html"),
)


def fingerprint(content: bytes) -> str:
    """The first 10 hex characters of the content's sha256."""
    return hashlib.sha256(content).hexdigest()[:10]


def built(tree, name: str):
    """A file of the built tree: the shell page at the root, a script under __neutrino/."""
    return tree / name if name == "index.html" else tree / "__neutrino" / name


def test_the_shell_page_is_at_the_root_and_the_scripts_under_their_folder(tmp_path):
    tree = build_share_page.assemble(tmp_path / "site")

    assert (tree / "index.html").is_file()
    assert sorted(path.name for path in (tree / "__neutrino").iterdir()) == sorted(
        SCRIPTS
    )
    assert sorted(path.name for path in tree.iterdir() if path.is_file()) == [
        "_headers",
        "edgeone.json",
        "index.html",
    ]


def test_each_script_is_named_by_its_content(tmp_path):
    tree = build_share_page.assemble(tmp_path / "site")

    assert built(tree, "shim.js").read_bytes() == (SOURCE_DIR / "shim.js").read_bytes()
    for script, namer in SCRIPT_NAMERS:
        plain = f'"/__neutrino/{script}"'.encode()
        named = (
            f'"/__neutrino/{script}?v={fingerprint(built(tree, script).read_bytes())}"'
        )
        source = (SOURCE_DIR / namer).read_bytes()
        assert built(tree, namer).read_bytes() == source.replace(plain, named.encode())
        assert built(tree, namer).read_text(encoding="utf-8").count(named) == 1


def test_the_source_names_each_script_once_with_no_fingerprint():
    for script, namer in SCRIPT_NAMERS:
        source = (SOURCE_DIR / namer).read_text(encoding="utf-8")
        assert source.count(f'"/__neutrino/{script}"') == 1, (script, namer)
        assert f"/__neutrino/{script}?" not in source


def test_a_changed_shim_changes_every_address_above_it(tmp_path, monkeypatch):
    before = build_share_page.assemble(tmp_path / "before")
    again = build_share_page.assemble(tmp_path / "again")
    source = tmp_path / "share_page"
    shutil.copytree(SOURCE_DIR, source)
    with (source / "shim.js").open("a", encoding="utf-8") as shim:
        shim.write("// changed\n")
    monkeypatch.setattr(build_share_page, "SHARE_PAGE_DIR", source)
    after = build_share_page.assemble(tmp_path / "after")

    for name in ("index.html", "shell.js", "sw.js", "shim.js"):
        first = built(before, name).read_bytes()
        assert built(again, name).read_bytes() == first
        assert built(after, name).read_bytes() != first, name


@pytest.mark.parametrize(
    "namer, count",
    [(b'fetch("/shim.js");', 0), (b'"/__neutrino/shim.js" "/__neutrino/shim.js"', 2)],
)
def test_a_file_that_does_not_name_a_script_once_fails_the_build(namer, count):
    with pytest.raises(SystemExit, match=f'names "/__neutrino/shim.js" {count} times'):
        build_share_page.fingerprint_address(namer, "shim.js", b"")


def test_both_hosts_send_service_worker_allowed_with_the_registered_worker(tmp_path):
    tree = build_share_page.assemble(tmp_path / "site")
    shell = (tree / "__neutrino" / "shell.js").read_text(encoding="utf-8")
    registered = re.search(
        r'navigator\.serviceWorker\.register\("(/__neutrino/sw\.js)\?v=[0-9a-f]{10}"',
        shell,
    )
    assert registered
    path = registered.group(1)

    assert f"\n{path}\n  Service-Worker-Allowed: /\n" in (tree / "_headers").read_text()
    rules = json.loads((tree / "edgeone.json").read_text())["headers"]
    (rule,) = [rule for rule in rules if rule["source"] == path]
    assert {"key": "Service-Worker-Allowed", "value": "/"} in rule["headers"]
