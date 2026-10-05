"""The Installed-Size every .deb of the project's names."""

import os

from shared import deb_build


def test_files_count_in_kib_rounded_up_and_the_control_directory_not(tmp_path):
    (tmp_path / "DEBIAN").mkdir()
    (tmp_path / "DEBIAN/control").write_bytes(b"x" * 5000)
    (tmp_path / "opt/neutrino").mkdir(parents=True)
    (tmp_path / "opt/neutrino/one").write_bytes(b"x" * 1)
    (tmp_path / "opt/neutrino/two").write_bytes(b"x" * 2049)
    os.symlink("one", tmp_path / "opt/neutrino/link")

    # two directories, one link: one KiB each; the files 1 and 3 KiB.
    assert deb_build.installed_size_kib(tmp_path) == 3 + 1 + 3
