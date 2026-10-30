"""Installing, removing and verifying one ``hub`` module.

What these pin: the recipe's ``verify`` is run and its exit read; a received
file is checked against the artifact's ``sha256:`` digest; each artifact
kind lands the one way every module shares: an archive unpacked under its
directory and sealed, or beside what the module's directory holds when it
names none, an msi or a pkg kept under its directory and handed to the
system's installer, a zstd file kept as it came, a program kept where its
runner says and made executable; an unknown kind is ``install_failed``; a
``hub`` entry's system packages are installed by name before any artifact;
and another version is staged beside each file it replaces as ``.new``,
swapped in with each replaced file kept as ``.old``, the ``.old`` files
dropped or put back, and a failed ``verify`` named by its own output.
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
    drop_replaced,
    received_artifacts,
    remove_staged,
    stage_artifact,
    swap_back,
    swap_in,
    unpacked_paths,
    program_stamp,
    verify_detail,
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


def test_a_verify_commands_program_is_its_first_word_or_quoted_part(
    tmp_path, monkeypatch
):
    program = tmp_path / "state dir" / "code"
    program.parent.mkdir()
    program.write_text("x")
    found = os.stat(program)
    stamp = (str(program), found.st_mtime_ns, found.st_size, found.st_ino)
    monkeypatch.setenv("NEUTRINO_TEST_STATE", str(tmp_path / "state dir"))

    assert program_stamp(f'"{program}" --version') == stamp
    assert program_stamp('"$NEUTRINO_TEST_STATE/code" --version') == stamp
    assert program_stamp(f"{tmp_path}/none --version") is None
    assert program_stamp("podman --version && runc --version") is None
    assert program_stamp("") is None


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


# --- another version ---


def test_an_archive_with_a_directory_stages_beside_it_and_swaps_in(tmp_path):
    module = tmp_path / "demo"
    (module / "server").mkdir(parents=True)
    (module / "server" / "run").write_text("1.0")
    archive = tarball(tmp_path / "server.tar.gz", {"top/run": b"2.0"})
    artifact = {"name": "server", "kind": "tar_gz", "directory": "server"}

    pairs = stage_artifact(artifact, archive, module_dir=str(module), join=os.path.join)
    swapped = swap_in(pairs)

    target = str(module / "server")
    assert pairs == [(target, target + ".new")]
    assert (module / "server" / "run").read_text() == "2.0"
    assert (module / "server.old" / "run").read_text() == "1.0"
    drop_replaced(pairs)
    assert sorted(os.listdir(module)) == ["server"]
    assert swapped == pairs


def test_an_archive_with_no_directory_swaps_each_of_its_files(tmp_path):
    module = tmp_path / "demo"
    module.mkdir()
    (module / "code").write_text("1.0")
    (module / "tokens").mkdir()
    archive = tarball(tmp_path / "cli.tar.gz", {"code": b"2.0"})

    pairs = stage_artifact(
        {"name": "cli", "kind": "tar_gz"},
        archive,
        module_dir=str(module),
        join=os.path.join,
    )
    swapped = swap_in(pairs)
    swap_back(swapped)

    assert (module / "code").read_text() == "1.0"
    remove_staged(pairs)
    assert sorted(os.listdir(module)) == ["code", "tokens"]


def test_a_program_is_staged_executable_and_put_back_on_a_failed_switch(tmp_path):
    target = tmp_path / "gitea"
    target.write_text("1.0")
    received = tmp_path / "received"
    received.write_text("2.0")

    pairs = stage_artifact(
        {"name": "gitea", "kind": "binary"},
        str(received),
        module_dir=str(tmp_path / "module"),
        join=os.path.join,
        binary_target=str(target),
    )
    swapped = swap_in(pairs)

    assert target.read_text() == "2.0"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o755
    swap_back(swapped)
    assert target.read_text() == "1.0"
    assert sorted(os.listdir(tmp_path)) == ["gitea", "received"]


def test_an_artifact_that_cannot_be_staged_is_install_failed(tmp_path):
    with pytest.raises(ModuleApplyError) as refused:
        stage_artifact(
            {"name": "podman", "kind": "msi", "directory": "podman"},
            str(tmp_path / "x"),
            module_dir=str(tmp_path),
            join=os.path.join,
        )

    assert refused.value.code == "install_failed"


def test_a_failed_verify_is_named_by_its_own_output():
    assert verify_detail("true") == ""
    assert verify_detail("echo broken >&2; exit 3") == "broken"
    assert verify_detail("exit 4") == "exit 4"
    assert verify_detail("") == "no verify command"
