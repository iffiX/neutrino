"""The two files a release writes over all of its others: latest.json, which
names it, and SHA256SUMS, which lists every file of it."""

import hashlib
import json

import build_checksums
import build_sources


def test_latest_json_names_the_release_by_its_tag_and_version(tmp_path):
    build_checksums.write_latest(tmp_path, "9.9.9")

    assert json.loads((tmp_path / "latest.json").read_text()) == {
        "tag": "v9.9.9",
        "version": "9.9.9",
    }


def test_sha256sums_lists_every_file_and_latest_json_among_them(tmp_path):
    for name in ("neutrino-hub_9.9.9_amd64.deb", "neutrino-hub_9.9.9_amd64-cn.deb"):
        (tmp_path / name).write_bytes(name.encode())
    build_checksums.write_latest(tmp_path, "9.9.9")

    build_checksums.write_checksums(tmp_path)

    listed = dict(
        reversed(line.split("  ", 1))
        for line in (tmp_path / "SHA256SUMS").read_text().splitlines()
    )
    assert sorted(listed) == [
        "latest.json",
        "neutrino-hub_9.9.9_amd64-cn.deb",
        "neutrino-hub_9.9.9_amd64.deb",
    ]
    for name, digest in listed.items():
        assert digest == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()


def test_the_version_is_the_one_the_packages_declare():
    assert build_checksums.version is build_sources.version
