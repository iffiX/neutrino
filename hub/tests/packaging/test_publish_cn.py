"""``packaging/ci/publish_cn.py`` against a fake Gitee API.

The fake keeps releases and their attachments in memory and records every
call, so what is asserted is the order the publish works in: every limit
checked before the first request that changes Gitee, the earlier releases'
attachments deleted before the first upload, and a second run for the same
tag reusing its release and uploading only what is missing.
"""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import urllib.parse
from pathlib import Path

import pytest

PUBLISH = Path(__file__).resolve().parents[3] / "packaging" / "ci" / "publish_cn.py"
TOKEN = "fake-token-0123"  # scan: allow
TAG = "v9.9.9"


# Stand-ins for the five pinned cc-switch files, small and pinned by their own
# hashes, so a release can carry them without a download.
CC_SWITCH_FILES = {
    f"cc-switch-cli-v5.10.4-{asset}": asset.encode()
    for asset in (
        "linux-x64-musl.tar.gz",
        "linux-arm64-musl.tar.gz",
        "windows-x64.zip",
        "darwin-arm64.tar.gz",
        "darwin-x64.tar.gz",
    )
}
CC_SWITCH_LICENSE = "cc-switch-cli-v5.10.4-LICENSE.txt"


@pytest.fixture(scope="module")
def publish_cn():
    spec = importlib.util.spec_from_file_location("publish_cn", PUBLISH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def pinned_cc_switch(publish_cn, monkeypatch):
    """The cc-switch pins named by the stand-ins' own hashes."""
    pins = {
        name: (f"https://upstream.invalid/{name}", hashlib.sha256(data).hexdigest())
        for name, data in CC_SWITCH_FILES.items()
    }
    monkeypatch.setattr(publish_cn.cc_switch_assets, "release_files", lambda: pins)
    return pins


class FakeGitee:
    """Releases and their attachments, and every call made."""

    def __init__(self):
        self.calls = []
        self.releases = {}
        self._next_id = 100

    def add_release(self, tag, files=()):
        release_id = self._new_id()
        self.releases[release_id] = {
            "tag_name": tag,
            "files": [
                {"id": self._new_id(), "name": name, "size": size}
                for name, size in files
            ],
        }
        return release_id

    def changes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def send(self, method, url, body, headers):
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.split("/repos/iffiX/neutrino", 1)[1]
        query = urllib.parse.parse_qs(parsed.query)
        self.calls.append((method, path))
        if method == "GET":
            assert query["access_token"] == [TOKEN]
        else:
            assert TOKEN.encode() in (body or b"") or query["access_token"] == [TOKEN]
        page = int(query.get("page", ["1"])[0])
        if method == "GET" and path == "/releases":
            listed = [
                {"id": key, "tag_name": value["tag_name"]}
                for key, value in self.releases.items()
            ]
            return 200, json.dumps(listed if page == 1 else []).encode()
        found = re.fullmatch(r"/releases/tags/(.+)", path)
        if method == "GET" and found:
            for key, value in self.releases.items():
                if value["tag_name"] == found.group(1):
                    return (
                        200,
                        json.dumps({"id": key, "tag_name": found.group(1)}).encode(),
                    )
            return 404, b'{"message":"Not Found"}'
        if method == "POST" and path == "/releases":
            fields = urllib.parse.parse_qs(body.decode())
            release_id = self.add_release(fields["tag_name"][0])
            return 201, json.dumps({"id": release_id}).encode()
        found = re.fullmatch(r"/releases/(\d+)/attach_files", path)
        if found:
            release = self.releases[int(found.group(1))]
            if method == "GET":
                return 200, json.dumps(release["files"] if page == 1 else []).encode()
            name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
            content = body.split(b"\r\n\r\n", 2)[2].rsplit(b"\r\n--", 1)[0]
            entry = {"id": self._new_id(), "name": name, "size": len(content)}
            release["files"].append(entry)
            return 201, json.dumps(entry).encode()
        found = re.fullmatch(r"/releases/(\d+)/attach_files/(\d+)", path)
        if method == "DELETE" and found:
            release = self.releases[int(found.group(1))]
            release["files"] = [
                item for item in release["files"] if item["id"] != int(found.group(2))
            ]
            return 204, b""
        return 500, f"unexpected {method} {path}".encode()

    def _new_id(self):
        self._next_id += 1
        return self._next_id


def _dist(tmp_path, extra=None):
    """A directory of release files: a small mainland tree and two packages."""
    tree = tmp_path / "staged" / "neutrino-9.9.9"
    (tree / "hub").mkdir(parents=True)
    (tree / "hub" / "pyproject.toml").write_text('version = "9.9.9"\n')
    (tree / "EDITION").write_text("cn\n")
    (tree / "third_party").mkdir()
    (tree / "third_party" / "upstream.tar.gz").write_bytes(b"upstream")
    dist = tmp_path / "dist"
    dist.mkdir()
    with tarfile.open(dist / "neutrino-9.9.9-cn-source.tar.gz", "w:gz") as archive:
        archive.add(tree, arcname="neutrino-9.9.9")
    (dist / "neutrino-hub_9.9.9_amd64.deb").write_bytes(b"hub package")
    (dist / "install.sh").write_bytes(b'EDITION="cn"\n')
    for name, data in CC_SWITCH_FILES.items():
        (dist / name).write_bytes(data)
    (dist / CC_SWITCH_LICENSE).write_text("MIT License\n")
    for name, size in (extra or {}).items():
        with open(dist / name, "wb") as handle:
            handle.truncate(size)
    return dist


@pytest.fixture
def run(publish_cn, tmp_path, monkeypatch):
    pushed = []
    monkeypatch.setattr(
        publish_cn,
        "push_tree",
        lambda tree, tag, key, work: pushed.append((tree, tag)),
    )

    def invoke(gitee, dist, *, is_dry_run=False):
        work = tmp_path / f"work{len(pushed)}{len(gitee.calls)}"
        work.mkdir()
        publish_cn.publish(
            tag=TAG,
            notes="feature: something",
            files=publish_cn.release_files(dist),
            work=work,
            client=publish_cn.GiteeReleaseClient(token=TOKEN, send=gitee.send),
            ssh_key="key",
            is_dry_run=is_dry_run,
        )

    invoke.pushed = pushed
    return invoke


def test_an_attachment_over_100_mb_fails_before_anything_changes(run, tmp_path):
    gitee = FakeGitee()
    dist = _dist(tmp_path, {"neutrino-hub-9.9.9-macos-arm64.pkg": 100_000_001})

    with pytest.raises(SystemExit) as refused:
        run(gitee, dist)

    assert str(refused.value) == (
        "neutrino-hub-9.9.9-macos-arm64.pkg is 100000001 bytes, over Gitee's "
        "limit of 100000000 bytes for one attachment"
    )
    assert gitee.calls == []
    assert run.pushed == []


def test_a_set_over_1_gb_fails_before_anything_changes(run, tmp_path):
    gitee = FakeGitee()
    dist = _dist(tmp_path, {f"part{index}.msi": 99_000_000 for index in range(11)})

    with pytest.raises(SystemExit) as refused:
        run(gitee, dist)

    assert "over Gitee's limit of 1000000000 bytes for all attachments" in str(
        refused.value
    )
    assert re.search(r"the 20 files are 10890\d+ bytes", str(refused.value))
    assert gitee.calls == []
    assert run.pushed == []


def test_a_tree_file_over_50_mb_fails_before_anything_changes(
    publish_cn, run, tmp_path
):
    gitee = FakeGitee()
    dist = _dist(tmp_path)
    work = tmp_path / "big"
    work.mkdir()
    tree = work / "neutrino-9.9.9"
    tree.mkdir()
    with open(tree / "blob.bin", "wb") as handle:
        handle.truncate(50_000_001)
    archive = dist / "neutrino-9.9.9-cn-source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(tree, arcname="neutrino-9.9.9")

    with pytest.raises(SystemExit) as refused:
        run(gitee, dist)

    assert str(refused.value) == (
        "blob.bin is 50000001 bytes, over Gitee's limit of 50000000 bytes "
        "for one file"
    )
    assert gitee.calls == []


def test_the_earlier_attachments_go_before_the_first_upload(run, tmp_path):
    gitee = FakeGitee()
    gitee.add_release("v9.9.8", [("neutrino-hub_9.9.8_amd64.deb", 5), ("x", 1)])
    gitee.add_release("v9.9.7", [("neutrino-hub_9.9.7_amd64.deb", 5)])

    run(gitee, _dist(tmp_path))

    changes = gitee.changes()
    deletes = [index for index, call in enumerate(changes) if call[0] == "DELETE"]
    uploads = [
        index
        for index, call in enumerate(changes)
        if call[0] == "POST" and call[1].endswith("/attach_files")
    ]
    assert len(deletes) == 3
    assert len(uploads) == 9
    assert max(deletes) < min(uploads)
    assert changes[max(deletes) + 1] == ("POST", "/releases")
    assert run.pushed[0][1] == TAG
    for release in gitee.releases.values():
        if release["tag_name"] != TAG:
            assert release["files"] == []


def test_the_tree_is_pushed_without_third_party(publish_cn, run, tmp_path):
    run(FakeGitee(), _dist(tmp_path))

    tree = run.pushed[0][0]
    assert (tree / "EDITION").read_text() == "cn\n"
    assert not (tree / "third_party").exists()


def test_a_second_run_for_the_tag_reuses_its_release_and_uploads_what_is_missing(
    run, tmp_path
):
    gitee = FakeGitee()
    dist = _dist(tmp_path)
    held = dist / "neutrino-hub_9.9.9_amd64.deb"
    release_id = gitee.add_release(TAG, [(held.name, held.stat().st_size)])

    run(gitee, dist)

    changes = gitee.changes()
    assert ("POST", "/releases") not in changes
    uploaded = [call for call in changes if call[1].endswith("/attach_files")]
    assert len(uploaded) == 8
    names = sorted(item["name"] for item in gitee.releases[release_id]["files"])
    assert names == sorted(path.name for path in dist.iterdir())

    gitee.calls.clear()
    run(gitee, dist)

    assert gitee.changes() == []


def test_a_file_of_the_same_name_and_another_size_is_replaced(run, tmp_path):
    gitee = FakeGitee()
    dist = _dist(tmp_path)
    release_id = gitee.add_release(TAG, [("install.sh", 1)])

    run(gitee, dist)

    (entry,) = [
        item
        for item in gitee.releases[release_id]["files"]
        if item["name"] == "install.sh"
    ]
    assert entry["size"] == (dist / "install.sh").stat().st_size


def test_a_dry_run_changes_nothing_and_pushes_nothing(run, tmp_path):
    gitee = FakeGitee()
    gitee.add_release("v9.9.8", [("neutrino-hub_9.9.8_amd64.deb", 5)])

    run(gitee, _dist(tmp_path), is_dry_run=True)

    assert gitee.changes() == []
    assert run.pushed == []


def test_the_same_archive_makes_the_same_parentless_commit(publish_cn, tmp_path):
    dist = _dist(tmp_path)
    heads = []
    for attempt in ("first", "second"):
        work = tmp_path / attempt
        work.mkdir()
        tree, stamp = publish_cn.unpack_tree(publish_cn.release_files(dist), work)
        publish_cn.commit_tree(tree, TAG, stamp)
        heads.append(
            subprocess.run(
                ["git", "rev-list", "--parents", "-n", "1", TAG],
                cwd=tree,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
        )

    assert heads[0] == heads[1]
    assert len(heads[0]) == 1


def test_the_push_checks_the_pinned_host_key(publish_cn, tmp_path, monkeypatch):
    from shared.constants import PACKAGING_GITEE_PUSH_URL, PACKAGING_GITEE_SSH_HOST_KEY

    seen = []
    monkeypatch.setattr(
        publish_cn,
        "_git",
        lambda command, tree, environment: seen.append((command, environment)),
    )

    publish_cn.push_tree(tmp_path, TAG, "-----KEY-----", tmp_path)

    ((command, environment),) = seen
    assert command[:4] == ["git", "push", "--force", PACKAGING_GITEE_PUSH_URL]
    assert "HEAD:refs/heads/main" in command
    assert f"refs/tags/{TAG}:refs/tags/{TAG}" in command
    ssh = environment["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=yes" in ssh
    known_hosts = ssh.split("UserKnownHostsFile=")[1].split()[0]
    assert Path(known_hosts).read_text().strip() == PACKAGING_GITEE_SSH_HOST_KEY
    assert oct((tmp_path / "gitee_key").stat().st_mode & 0o777) == "0o600"


def test_a_refusal_names_the_call_and_never_the_token(publish_cn):
    def refuse(method, url, body, headers):
        return 403, f"token {TOKEN} lacks projects".encode()

    client = publish_cn.GiteeReleaseClient(token=TOKEN, send=refuse)

    with pytest.raises(SystemExit) as refused:
        client.delete_attachment(1, 2)

    assert str(refused.value) == (
        "Gitee answered 403 to DELETE /releases/1/attach_files/2: "
        "token *** lacks projects"
    )


def test_check_only_reads_the_files_and_reaches_nothing(
    publish_cn, tmp_path, monkeypatch, capsys
):
    dist = _dist(tmp_path)
    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.setattr(
        publish_cn.sys, "argv", ["publish_cn.py", "--check-only", "--dist", str(dist)]
    )

    assert publish_cn.main() == 0
    assert capsys.readouterr().out.strip() == "9 files are within Gitee's limits"


def test_check_only_needs_no_secret_and_no_network(tmp_path):
    """The real pins: a cc-switch file that is not the pinned one is refused
    by name, with no token and nothing fetched."""
    dist = _dist(tmp_path)

    result = subprocess.run(
        [sys.executable, str(PUBLISH), "--check-only", "--dist", str(dist)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert result.stderr.strip().startswith(
        "cc-switch-cli-v5.10.4-darwin-arm64.tar.gz hashes to "
    )


@pytest.mark.parametrize(
    "change, said",
    [
        (
            "missing",
            "the release carries no cc-switch-cli-v5.10.4-darwin-x64.tar.gz",
        ),
        ("tampered", "cc-switch-cli-v5.10.4-darwin-x64.tar.gz hashes to "),
        ("licence", "the release carries no cc-switch-cli-v5.10.4-LICENSE.txt"),
    ],
)
def test_a_release_without_the_pinned_cc_switch_files_is_refused_before_anything(
    run, tmp_path, change, said
):
    gitee = FakeGitee()
    dist = _dist(tmp_path)
    if change == "missing":
        (dist / "cc-switch-cli-v5.10.4-darwin-x64.tar.gz").unlink()
    if change == "tampered":
        (dist / "cc-switch-cli-v5.10.4-darwin-x64.tar.gz").write_bytes(b"other")
    if change == "licence":
        (dist / CC_SWITCH_LICENSE).unlink()

    with pytest.raises(SystemExit) as refused:
        run(gitee, dist)

    assert str(refused.value).startswith(said)
    assert gitee.calls == []
    assert run.pushed == []


def test_the_cc_switch_files_go_up_beside_the_packages(run, tmp_path):
    gitee = FakeGitee()

    run(gitee, _dist(tmp_path))

    (release,) = [r for r in gitee.releases.values() if r["tag_name"] == TAG]
    names = {item["name"] for item in release["files"]}
    assert set(CC_SWITCH_FILES) <= names
    assert CC_SWITCH_LICENSE in names
