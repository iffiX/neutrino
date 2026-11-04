"""The mark that the module installed the computer's Podman.

What these pin: the mark written root-only into the module's directory,
the directory made root-only where it is missing, a second write keeping
one mark, and a forget of a missing mark ending quietly.
"""

import os

from neutrino_agent.modules.podman.package_mark import PodmanPackageMark


def test_the_mark_is_one_root_only_file_in_the_module_s_directory(tmp_path):
    module_dir = tmp_path / "state" / "podman"
    mark = PodmanPackageMark(module_dir=str(module_dir))

    assert mark.is_kept() is False
    mark.keep()
    mark.keep()

    assert mark.path == str(module_dir / "package_mark")
    assert mark.is_kept() is True
    assert os.listdir(module_dir) == ["package_mark"]
    assert oct((module_dir / "package_mark").stat().st_mode & 0o777) == oct(0o600)
    assert oct(module_dir.stat().st_mode & 0o777) == oct(0o700)


def test_a_forgotten_mark_is_gone_and_a_missing_one_forgets_quietly(tmp_path):
    mark = PodmanPackageMark(module_dir=str(tmp_path / "podman"))

    mark.forget()
    mark.keep()
    mark.forget()

    assert mark.is_kept() is False
    assert os.listdir(tmp_path / "podman") == []
