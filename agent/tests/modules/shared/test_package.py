"""Installing, removing and verifying one ``hub`` module.

What these pin: the recipe's ``verify`` is run and its exit read; a received
file is checked against the artifact's ``sha256:`` digest; each artifact
kind lands the one way every module shares: an archive unpacked under its
directory and sealed, or beside what the module's directory holds when it
names none, an msi or a pkg kept under its directory and handed to the
system's installer, a zstd file kept as it came, a program kept where its
runner says and made executable; an unknown kind is ``install_failed``; and
a ``hub`` entry's system packages are installed by name before any
artifact.
"""

import io
import os
import stat
import subprocess
import tarfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared import base as base_module
from neutrino_agent.modules.shared import package as package_module
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.package import (
    artifacts_of,
    check_received,
    digest_hex,
    keep_artifact,
    npm_artifact,
    place_binary,
    received_artifacts,
    unpacked_paths,
    verify_passes,
)
from neutrino_agent.platforms.base import AgentPlatform

RECIPE = {
    "runner": "demo",
    "method": "hub",
    "params": {
        "version": "1.0",
        "artifacts": [
            {
                "name": "node",
                "kind": "tar_gz",
                "directory": "node",
                "digest": "sha256:aa",
            },
            {
                "name": "demo",
                "kind": "npm",
                "package": "@demo/demo",
                "digest": "sha512-x",
                "sources": ["https://registry.example"],
            },
        ],
        "packages": ["git"],
        "verify": "demo --version",
    },
}


class StatePlatform(AgentPlatform):
    """A platform whose state root is a temporary directory."""

    os_name = "linux"

    def __init__(self, root):
        self.root = str(root)
        self.installed: list = []
        self.opened: list = []
        self.labelled: list = []

    def agent_var_dir(self):
        return self.root

    def install_system_packages(self, names):
        self.installed.append(list(names))
        return ""

    def open_to_accounts(self, directory):
        self.opened.append(directory)

    def label_programs(self, path):
        self.labelled.append(path)


class DemoRunner(ModuleRunner):
    runner = "demo"
    name = "demo"

    def binary_path(self, recipe, artifact):
        return os.path.join(self.module_dir, "bin", "demo")


def tarball(path, members: dict) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def test_verify_passes_runs_the_recipes_command_and_reads_its_exit(monkeypatch):
    seen: list = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0 if "ok" in command else 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert verify_passes("smbd -V ok") is True
    assert verify_passes("smbd -V") is False
    assert verify_passes("") is False
    assert seen == ["smbd -V ok", "smbd -V"]


def test_the_npm_artifact_is_not_received_and_is_found_by_its_kind():
    assert [artifact["name"] for artifact in artifacts_of(RECIPE)] == ["node", "demo"]
    assert [artifact["name"] for artifact in received_artifacts(RECIPE)] == ["node"]
    assert npm_artifact(RECIPE)["package"] == "@demo/demo"
    assert npm_artifact({"params": {}}) == {}
    assert artifacts_of({}) == []


def test_a_received_file_is_checked_against_the_artifacts_digest():
    artifact = {"name": "node", "digest": "sha256:ABC"}

    assert digest_hex("sha256:ABC") == "abc"
    assert digest_hex("sha512-x") == ""
    assert check_received(artifact, {"path": "/p", "sha256": "abc"}) is None
    assert check_received(artifact, {"path": "/p", "sha256": "abd"}) == {
        "code": "package_digest_mismatch",
        "params": {"artifact": "node"},
    }
    assert check_received({"name": "x", "digest": ""}, {"sha256": ""})["code"] == (
        "package_digest_mismatch"
    )


def test_an_archive_lands_under_its_directory_sealed_and_opened(tmp_path):
    platform = StatePlatform(tmp_path / "state")
    runner = DemoRunner(platform=platform)
    archive = tarball(tmp_path / "node.tar.gz", {"node-v22/bin/node": b"#!node"})

    runner.install_artifact(RECIPE, RECIPE["params"]["artifacts"][0], archive)

    node = tmp_path / "state" / "demo" / "node"
    assert (node / "bin" / "node").read_bytes() == b"#!node"
    assert stat.S_IMODE(node.stat().st_mode) == 0o555
    assert platform.opened == [str(tmp_path / "state" / "demo")]
    assert platform.labelled == [str(node)]


def test_an_archive_that_names_no_directory_lands_beside_what_is_there(tmp_path):
    platform = StatePlatform(tmp_path / "state")
    runner = DemoRunner(platform=platform)
    kept = tmp_path / "state" / "demo" / "tokens"
    kept.mkdir(parents=True)
    (kept / "lab.token").write_text("t")
    archive = tarball(tmp_path / "cli.tar.gz", {"code": b"#!cli"})

    runner.install_artifact(
        RECIPE, {"name": "cli", "kind": "tar_gz", "digest": "sha256:aa"}, archive
    )

    module = tmp_path / "state" / "demo"
    assert sorted(os.listdir(module)) == ["code", "tokens"]
    assert (kept / "lab.token").read_text() == "t"
    assert platform.labelled == [str(module)]


def test_the_unpacks_of_a_recipe_are_its_archives_places_once_each():
    recipe = {
        "params": {
            "artifacts": [
                {"name": "server", "kind": "tar_gz", "directory": "server"},
                {"name": "node", "kind": "zip", "directory": "node"},
                {"name": "cli", "kind": "tar_gz"},
                {"name": "again", "kind": "tar_gz", "directory": "node"},
                {"name": "odd", "kind": "tar_gz", "directory": "../up"},
                {"name": "app", "kind": "npm", "directory": "app"},
                {"name": "msi", "kind": "msi", "directory": "msi"},
            ]
        }
    }

    assert unpacked_paths(recipe, module_dir="/m", join=os.path.join) == [
        "/m/server",
        "/m/node",
        "/m",
    ]
    assert unpacked_paths({}, module_dir="/m", join=os.path.join) == []


def test_a_broken_archive_is_install_failed(tmp_path):
    runner = DemoRunner(platform=StatePlatform(tmp_path / "state"))
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not an archive")

    with pytest.raises(ModuleApplyError) as refused:
        runner.install_artifact(RECIPE, RECIPE["params"]["artifacts"][0], str(junk))

    assert refused.value.code == "install_failed"


def test_a_directory_that_is_not_a_plain_name_is_install_failed(tmp_path):
    runner = DemoRunner(platform=StatePlatform(tmp_path / "state"))

    with pytest.raises(ModuleApplyError) as refused:
        runner.install_artifact(
            RECIPE,
            {"name": "node", "kind": "zip", "directory": "../x", "digest": ""},
            str(tmp_path / "none.zip"),
        )

    assert refused.value.code == "install_failed"


@pytest.mark.parametrize(
    "kind, suffix, installer",
    [("msi", ".msi", "install_msi"), ("pkg", ".pkg", "install_pkg")],
)
def test_an_installer_package_is_kept_then_handed_to_the_system(
    tmp_path, monkeypatch, kind, suffix, installer
):
    handed: list = []
    monkeypatch.setattr(
        base_module.installers,
        installer,
        lambda path, **kwargs: handed.append((path, sorted(kwargs))),
    )
    runner = DemoRunner(platform=StatePlatform(tmp_path / "state"))
    received = tmp_path / "received"
    received.write_bytes(b"package")

    runner.install_artifact(
        RECIPE,
        {"name": "app", "kind": kind, "directory": "app", "digest": "sha256:aa"},
        str(received),
    )

    kept = tmp_path / "state" / "demo" / "app" / f"app{suffix}"
    assert kept.read_bytes() == b"package"
    assert not received.exists()
    assert [path for path, _ in handed] == [str(kept)]
    assert handed[0][1] == (["log_path"] if kind == "msi" else [])


def test_a_zstd_file_is_kept_as_it_came_and_installed_by_nothing(tmp_path):
    kept = keep_artifact(
        {"name": "image", "kind": "raw_zst", "directory": "image"},
        _received(tmp_path, b"\x28\xb5\x2f\xfd"),
        module_dir=str(tmp_path / "podman"),
        join=os.path.join,
    )

    assert kept == str(tmp_path / "podman" / "image" / "image.raw.zst")
    assert (
        package_module.kept_artifact_path(
            str(tmp_path / "podman"), "image", "raw_zst", os.path.join
        )
        == kept
    )


def test_a_program_is_kept_where_its_runner_says_and_made_executable(tmp_path):
    runner = DemoRunner(platform=StatePlatform(tmp_path / "state"))

    runner.install_artifact(
        RECIPE,
        {"name": "demo", "kind": "binary", "digest": "sha256:aa"},
        _received(tmp_path, b"\x7fELF"),
    )

    program = tmp_path / "state" / "demo" / "bin" / "demo"
    assert program.read_bytes() == b"\x7fELF"
    assert stat.S_IMODE(program.stat().st_mode) == 0o755


def test_place_binary_replaces_the_program_in_one_rename(tmp_path):
    target = tmp_path / "bin" / "gitea"
    place_binary(_received(tmp_path, b"one"), str(target))
    place_binary(_received(tmp_path, b"two"), str(target))

    assert target.read_bytes() == b"two"
    assert os.listdir(tmp_path / "bin") == ["gitea"]


def test_a_runner_that_keeps_no_program_refuses_a_binary(tmp_path):
    class PlainRunner(ModuleRunner):
        name = "plain"

    with pytest.raises(ModuleApplyError) as refused:
        PlainRunner(platform=StatePlatform(tmp_path)).install_artifact(
            {}, {"name": "x", "kind": "binary"}, _received(tmp_path, b"x")
        )

    assert refused.value.code == "install_failed"


def test_an_unknown_kind_is_install_failed(tmp_path):
    with pytest.raises(ModuleApplyError) as refused:
        DemoRunner(platform=StatePlatform(tmp_path)).install_artifact(
            {}, {"name": "x", "kind": "rar"}, _received(tmp_path, b"x")
        )

    assert refused.value.code == "install_failed"
    assert "rar" in refused.value.params["detail"]


def test_a_hub_entrys_system_packages_install_by_name(tmp_path):
    platform = StatePlatform(tmp_path)
    runner = DemoRunner(platform=platform, log=lambda message: None)

    runner.install(RECIPE)
    runner.install({"params": {}})

    assert platform.installed == [["git"]]


def _received(tmp_path, data: bytes) -> str:
    path = tmp_path / f"received_{len(os.listdir(tmp_path))}"
    path.write_bytes(data)
    return str(path)
