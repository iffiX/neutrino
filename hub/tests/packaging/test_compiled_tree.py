"""The compiled hub's staging, with the compiler stood in for.

What the macOS and Windows packages share: a build environment of its own
that installs wheels only, the compiler excepted; the package copied with its
version stamped and its icons, never the checkout's own stamp; the panel
refused when it is not built; the data copied beside the compiled package;
and the agent cache seeded with the one package of the hub's own system and
machine while the manifest names them all.
"""

import json

import pytest

import compiled_tree
from shared.constants import PACKAGING_EDITION_ENV, PACKAGING_RELEASE_SITES_ENV


def test_the_staged_package_is_stamped_and_carries_its_icons(tmp_path, monkeypatch):
    monkeypatch.setattr(compiled_tree.venv_tree, "require_built_frontend", lambda: None)

    package = compiled_tree.stage_hub_tree(
        tmp_path, "9.9.9", "neutrino-hub-{version}-macos-arm64.pkg"
    )

    stamp = (package / "_version.py").read_text()
    assert 'HUB_VERSION = "9.9.9"' in stamp
    assert list((package / "data" / "resources").glob("*.png"))
    assert (package / "cli" / "entry.py").is_file()
    assert not list(package.rglob("__pycache__"))
    assert not (compiled_tree.HUB_ROOT / "neutrino_hub" / "_version.py").exists()


def test_a_package_without_its_panel_is_refused(tmp_path, monkeypatch):
    def refuse():
        raise SystemExit("the panel has not been built")

    monkeypatch.setattr(compiled_tree.venv_tree, "require_built_frontend", refuse)

    with pytest.raises(SystemExit):
        compiled_tree.stage_hub_tree(tmp_path, "9.9.9", "x")


def test_the_data_lands_beside_the_compiled_package(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    (tree / "neutrino_hub" / "data" / "manifests").mkdir(parents=True)
    (tree / "neutrino_hub" / "data" / "manifests" / "vscode.json").write_text("{}")
    asked = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        asked.append((entry, binary_name, kwargs))
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"")
        return dist

    monkeypatch.setattr(
        compiled_tree.nuitka_build, "compile_standalone", compile_standalone
    )

    dist = compiled_tree.compile_hub(
        tmp_path / "python3", tree, tmp_path / "build", "nhub", options=("--x",)
    )

    assert (dist / "neutrino_hub" / "data" / "manifests" / "vscode.json").is_file()
    ((entry, name, kwargs),) = asked
    assert entry == tree / "neutrino_hub" / "cli" / "entry.py"
    assert name == "nhub"
    assert kwargs["source_root"] == tree
    assert kwargs["options"][-1] == "--x"


@pytest.mark.parametrize(
    ("edition", "suffix"), [("intl", ""), ("cn", "-cn")], ids=["intl", "cn"]
)
def test_only_the_hubs_own_agent_is_seeded_and_every_one_is_named(
    tmp_path, monkeypatch, edition, suffix
):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)
    monkeypatch.setenv(PACKAGING_RELEASE_SITES_ENV, "1")
    agents = tmp_path / "agents"
    agents.mkdir()
    for name in ("SHA256SUMS",) + tuple(
        f"neutrino-agent-9.9.9-{platform}{held}.{extension}"
        for held in ("", "-cn")
        for platform, extension in (
            ("macos-arm64", "pkg"),
            ("windows-amd64", "msi"),
            ("1.x86_64", "rpm"),
        )
    ):
        (agents / name).write_bytes(name.encode())

    seeded = compiled_tree.seed_agent_cache(
        agents,
        tmp_path / "cache",
        tmp_path / "data",
        family="msi",
        machine="amd64",
    )

    assert seeded == (
        tmp_path / "cache" / f"neutrino-agent-9.9.9-windows-amd64{suffix}.msi"
    )
    assert [path.name for path in (tmp_path / "cache").iterdir()] == [seeded.name]
    manifest = json.loads((tmp_path / "data" / "agent_packages.json").read_text())
    assert {key: entry["name"] for key, entry in manifest.items()} == {
        "msi-amd64": f"neutrino-agent-9.9.9-windows-amd64{suffix}.msi",
        "pkg-arm64": f"neutrino-agent-9.9.9-macos-arm64{suffix}.pkg",
        "rpm-amd64": f"neutrino-agent-9.9.9-1.x86_64{suffix}.rpm",
    }


def test_an_empty_agent_directory_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "intl")
    (tmp_path / "agents").mkdir()

    with pytest.raises(SystemExit) as refused:
        compiled_tree.seed_agent_cache(
            tmp_path / "agents",
            tmp_path / "cache",
            tmp_path / "data",
            family="pkg",
            machine="arm64",
        )

    assert "no intl agent package" in str(refused.value)


def test_the_build_python_is_the_pinned_minor(monkeypatch):
    monkeypatch.setattr(compiled_tree.sys, "version_info", (3, 14, 0, "final", 0))

    with pytest.raises(SystemExit) as refused:
        compiled_tree.check_build_python()

    assert "3.13" in str(refused.value)


def test_the_build_environment_is_its_own_and_installs_wheels_only(
    tmp_path, monkeypatch
):
    commands = []
    monkeypatch.setattr(compiled_tree.venv_tree, "run", commands.append)
    monkeypatch.setattr(compiled_tree.sys, "executable", "/opt/python3.13/bin/python3")
    monkeypatch.setattr(compiled_tree.sys, "platform", "darwin")

    python = compiled_tree.make_build_environment(tmp_path / "venv")

    assert python == tmp_path / "venv" / "bin" / "python3"
    venv, *installs = commands
    assert venv == ["/opt/python3.13/bin/python3", "-m", "venv", str(tmp_path / "venv")]
    assert [command[:4] for command in installs] == [
        [str(python), "-m", "pip", "install"]
    ] * 2
    assert all("--only-binary=:all:" in command for command in installs)
    assert installs[0][-1] == "nuitka==4.2.1"
    assert installs[0][installs[0].index("--only-binary=:all:") + 1] == (
        "--no-binary=nuitka"
    )
    assert installs[1][-1] == str(compiled_tree.HUB_ROOT)
    assert not any("--no-binary" in argument for argument in installs[1])
