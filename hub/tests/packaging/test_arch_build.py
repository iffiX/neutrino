"""Running makepkg over a directory holding a PKGBUILD, with makepkg faked."""

from types import SimpleNamespace

import pytest

from shared import arch_build

BUILT = "x-1.0-1-x86_64.pkg.tar.zst"


@pytest.fixture
def makepkg(monkeypatch, tmp_path):
    """A makepkg that writes the file or refuses, and what it was run as."""
    runs = SimpleNamespace(calls=[], returncode=0, writes=BUILT)

    def run(command, *, cwd, capture_output, text, env):
        runs.calls.append((command, env))
        if runs.returncode == 0 and runs.writes:
            (cwd / runs.writes).write_bytes(b"package")
        return SimpleNamespace(
            returncode=runs.returncode, stdout="said on stdout", stderr="said on stderr"
        )

    monkeypatch.setattr(arch_build.subprocess, "run", run)
    monkeypatch.setattr(arch_build.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        arch_build.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="somebody")
    )
    return runs


def _build(tmp_path, **names):
    root = tmp_path / "root"
    root.mkdir()
    output = tmp_path / "out"
    output.mkdir()
    return arch_build.build_package(
        root, output, "somebody", built=BUILT, name=names.get("name", BUILT)
    )


def test_the_build_writes_the_format_every_release_lists(makepkg, tmp_path):
    """Debian's makepkg.conf names another one."""
    target = _build(tmp_path)

    ((command, env),) = makepkg.calls
    assert command[0] == "makepkg"
    assert env["PKGEXT"] == ".pkg.tar.zst"
    assert target.read_bytes() == b"package"


def test_a_cn_build_lands_under_the_release_name(makepkg, tmp_path):
    target = _build(tmp_path, name="x-1.0-1-x86_64-cn.pkg.tar.zst")

    assert target.name == "x-1.0-1-x86_64-cn.pkg.tar.zst"


def test_root_steps_down_to_the_account_with_runuser(makepkg, tmp_path, monkeypatch):
    monkeypatch.setattr(arch_build.os, "geteuid", lambda: 0)
    owners = []
    monkeypatch.setattr(
        arch_build.shutil, "chown", lambda path, user: owners.append(user)
    )

    _build(tmp_path)

    ((command, _),) = makepkg.calls
    assert command[:4] == ["runuser", "-u", "somebody", "--"]
    assert owners == ["somebody"]


def test_a_refusal_stops_the_build_with_what_makepkg_said(makepkg, tmp_path):
    makepkg.returncode = 1

    with pytest.raises(SystemExit) as refused:
        _build(tmp_path)

    assert "said on stdout" in str(refused.value)
    assert "said on stderr" in str(refused.value)


def test_a_file_under_another_name_stops_the_build(makepkg, tmp_path):
    makepkg.writes = "x-1.0-1-x86_64.pkg.tar.gz"

    with pytest.raises(SystemExit, match="wrote no .*found x-1.0-1-x86_64.pkg.tar.gz"):
        _build(tmp_path)


@pytest.mark.parametrize(
    "named, euid, account",
    [
        ("given", 0, "given"),
        ("given", 1000, "given"),
        ("", 0, arch_build.ARCH_BUILD_USER),
        ("", 1000, "somebody"),
    ],
)
def test_makepkg_runs_as_the_named_account_else_the_person_else_the_build_account(
    makepkg, monkeypatch, named, euid, account
):
    monkeypatch.setattr(arch_build.os, "geteuid", lambda: euid)

    assert arch_build.builder_account(named) == account
