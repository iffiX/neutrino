"""The applier's effects, with the system underneath replaced.

The rule with teeth is work-root ownership: gitea runs as the git account
and creates ``.ssh`` under its work root on start, so a root-owned root is a
crashloop. The applier owns the root on every apply, which is what heals a
box that installed with it owned wrong.
"""

from pathlib import Path

import pytest

from neutrino_hub.modules.gitea import ops as gitea_ops
from neutrino_hub.modules.gitea.ops import GiteaConfigApplier


class Chowns:
    def __init__(self):
        self.calls: list[tuple[Path, str | None, str | None]] = []

    def __call__(self, path, user=None, group=None):
        self.calls.append((Path(path), user, group))


@pytest.fixture()
def box(monkeypatch, tmp_path):
    chowns = Chowns()
    monkeypatch.setattr(gitea_ops, "GITEA_DIR", tmp_path / "gitea")
    monkeypatch.setattr(gitea_ops, "GITEA_CONF_LINK_PATH", tmp_path / "etc/app.ini")
    monkeypatch.setattr(gitea_ops, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(gitea_ops.shutil, "chown", chowns)
    monkeypatch.setattr(
        gitea_ops,
        "run",
        lambda *args, **kwargs: type("R", (), {"stdout": "inactive"})(),
    )
    return tmp_path, chowns


def test_apply_owns_the_work_root_and_precreates_ssh(box, monkeypatch):
    tmp_path, chowns = box
    monkeypatch.setattr(gitea_ops.pwd, "getpwnam", lambda name: object())

    GiteaConfigApplier().apply("[server]\n")

    ssh_dir = tmp_path / "gitea/.ssh"
    assert ssh_dir.is_dir()
    assert (tmp_path / "gitea", "git", "git") in chowns.calls
    assert (ssh_dir, "git", "git") in chowns.calls


def test_apply_without_the_git_account_leaves_the_work_root_alone(box, monkeypatch):
    tmp_path, chowns = box

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(gitea_ops.pwd, "getpwnam", missing)

    GiteaConfigApplier().apply("[server]\n")

    assert not (tmp_path / "gitea").exists()
    assert all(path.name != "gitea" for path, _, _ in chowns.calls)


def test_apply_heals_a_root_owned_work_root_that_already_exists(box, monkeypatch):
    """Apply runs on every upgrade, so an existing broken box heals on the
    next one rather than needing a reinstall."""
    tmp_path, chowns = box
    monkeypatch.setattr(gitea_ops.pwd, "getpwnam", lambda name: object())
    (tmp_path / "gitea").mkdir()

    GiteaConfigApplier().apply("[server]\n")

    assert (tmp_path / "gitea/.ssh").is_dir()
    assert (tmp_path / "gitea", "git", "git") in chowns.calls
