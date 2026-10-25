"""``packaging/ci/publish_cn.py`` against a fake CNB API.

The fake keeps releases and their files in memory and records every call;
a bare repository in a temporary directory stands in for CNB's git. What is
asserted is every file of the release uploaded to the tag's release, the
mainland tree and ``latest.json`` committed on ``main`` with the tag on it,
and a second run for the same tag reusing its release and uploading nothing
twice.
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
API = "https://api.cnb.invalid"
REPOSITORY = "iffi-X/neutrino"
UPLOADS = "https://uploads.cnb.invalid"


# Stand-ins for the five pinned cc-switch files, small and pinned by their own
# hashes, so a release can hold them without a download.
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


class FakeCnb:
    """Releases and their files, and every call made."""

    def __init__(self):
        self.calls = []
        self.releases = {}
        self._pending = {}
        self._next_id = 100

    def add_release(self, tag, assets=()):
        release_id = self._new_id()
        self.releases[release_id] = {
            "tag_name": tag,
            "assets": [{"name": name, "size": size} for name, size in assets],
        }
        return release_id

    def changes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def held(self, tag):
        (release,) = [r for r in self.releases.values() if r["tag_name"] == tag]
        return {asset["name"]: asset["size"] for asset in release["assets"]}

    def send(self, method, url, body, headers):
        parsed = urllib.parse.urlparse(url)
        if url.startswith(UPLOADS):
            assert "Authorization" not in headers
            token = parsed.path.strip("/")
            data = body.read_bytes() if isinstance(body, Path) else body
            assert int(headers["Content-Length"]) == len(data)
            self._pending[token]["size"] = len(data)
            self.calls.append((method, "upload"))
            return 200, b""
        assert url.startswith(f"{API}/{REPOSITORY}/-/releases")
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert headers["Accept"] == "application/vnd.cnb.api+json"
        path = parsed.path.split(f"/{REPOSITORY}/-/releases", 1)[1]
        self.calls.append((method, path))
        found = re.fullmatch(r"/tags/(.+)", path)
        if method == "GET" and found:
            tag = urllib.parse.unquote(found.group(1))
            for key, value in self.releases.items():
                if value["tag_name"] == tag:
                    return 200, json.dumps({"id": str(key), **value}).encode()
            return 404, b'{"errcode":404,"errmsg":"not found"}'
        if method == "POST" and path == "":
            fields = json.loads(body)
            assert fields["draft"] is False and fields["prerelease"] is False
            release_id = self.add_release(fields["tag_name"])
            return 201, json.dumps({"id": str(release_id), "assets": []}).encode()
        found = re.fullmatch(r"/(\d+)/asset-upload-url", path)
        if method == "POST" and found:
            fields = json.loads(body)
            assert fields["overwrite"] is True and fields["ttl"] == 0
            token = f"t{self._new_id()}"
            self._pending[token] = {
                "release": int(found.group(1)),
                "name": fields["asset_name"],
                "declared": fields["size"],
            }
            return (
                201,
                json.dumps(
                    {
                        "upload_url": f"{UPLOADS}/{token}",
                        "verify_url": (
                            f"/{REPOSITORY}/-/releases/{found.group(1)}"
                            f"/asset-upload-confirmation/{token}/{fields['asset_name']}"
                        ),
                        "expires_in_sec": 43200,
                    }
                ).encode(),
            )
        found = re.fullmatch(r"/(\d+)/asset-upload-confirmation/([^/]+)/(.+)", path)
        if method == "POST" and found:
            pending = self._pending.pop(found.group(2))
            assert pending["size"] == pending["declared"]
            release = self.releases[pending["release"]]
            release["assets"] = [
                asset for asset in release["assets"] if asset["name"] != pending["name"]
            ] + [{"name": pending["name"], "size": pending["size"]}]
            return 200, b""
        return 500, f"unexpected {method} {path}".encode()

    def _new_id(self):
        self._next_id += 1
        return self._next_id


def _dist(tmp_path, *, latest_tag=TAG):
    """A directory of release files: a small mainland tree, two packages of
    each edition, the scripts, cc-switch and latest.json."""
    tree = tmp_path / "staged" / "neutrino-9.9.9"
    (tree / "hub").mkdir(parents=True)
    (tree / "hub" / "pyproject.toml").write_text('version = "9.9.9"\n')
    (tree / "EDITION").write_text("cn\n")
    (tree / "third_party").mkdir()
    (tree / "third_party" / "upstream.tar.gz").write_bytes(b"upstream")
    dist = tmp_path / "dist"
    dist.mkdir()
    with tarfile.open(dist / "neutrino-9.9.9-cn-source.tar.xz", "w:xz") as archive:
        archive.add(tree, arcname="neutrino-9.9.9")
    (dist / "neutrino-9.9.9-source.tar.xz").write_bytes(b"full tree")
    (dist / "neutrino-hub_9.9.9_amd64.deb").write_bytes(b"hub package")
    (dist / "neutrino-hub_9.9.9_amd64-cn.deb").write_bytes(b"cn hub package")
    (dist / "install.sh").write_bytes(b'EDITION="intl"\n')
    (dist / "install-cn.sh").write_bytes(b'EDITION="cn"\n')
    for name, data in CC_SWITCH_FILES.items():
        (dist / name).write_bytes(data)
    (dist / CC_SWITCH_LICENSE).write_text("MIT License\n")
    (dist / "latest.json").write_text(
        json.dumps({"tag": latest_tag, "version": latest_tag[1:]}) + "\n"
    )
    return dist


def _git(*command, cwd):
    return subprocess.run(
        ["git", *command], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def remote(tmp_path):
    """CNB's repository: a bare repository holding one earlier commit."""
    bare = tmp_path / "cnb.git"
    _git(
        "init", "--quiet", "--bare", "--initial-branch", "main", str(bare), cwd=tmp_path
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "README.md").write_text("# Neutrino\n")
    _git("init", "--quiet", "--initial-branch", "main", cwd=seed)
    _git("add", "--all", cwd=seed)
    _git(
        "-c",
        "user.name=seed",
        "-c",
        "user.email=seed@example.invalid",
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "--message",
        "seed",
        cwd=seed,
    )
    _git("push", "--quiet", str(bare), "main", cwd=seed)
    return bare


@pytest.fixture
def run(publish_cn, tmp_path, remote):
    runs = []

    def invoke(cnb, dist, *, is_dry_run=False):
        work = tmp_path / f"work{len(runs)}"
        work.mkdir()
        runs.append(work)
        publish_cn.publish(
            tag=TAG,
            notes="feature: something",
            files=publish_cn.release_files(dist),
            work=work,
            client=publish_cn.CnbReleaseClient(
                token=TOKEN, api=API, repository=REPOSITORY, send=cnb.send
            ),
            git_url=str(remote),
            git_token=TOKEN,
            is_dry_run=is_dry_run,
        )

    return invoke


def test_every_file_of_the_release_goes_up_to_the_tags_release(run, tmp_path):
    cnb = FakeCnb()
    dist = _dist(tmp_path)

    run(cnb, dist)

    assert cnb.held(TAG) == {path.name: path.stat().st_size for path in dist.iterdir()}
    assert ("POST", "") in cnb.changes()


def test_the_tree_and_latest_json_are_one_commit_on_main_tagged(run, tmp_path, remote):
    run(FakeCnb(), _dist(tmp_path))

    files = _git("ls-tree", "-r", "--name-only", "main", cwd=remote).split()
    assert sorted(files) == ["EDITION", "hub/pyproject.toml", "latest.json"]
    assert json.loads(_git("show", "main:latest.json", cwd=remote)) == {
        "tag": TAG,
        "version": "9.9.9",
    }
    assert _git("rev-parse", f"{TAG}^{{commit}}", cwd=remote) == _git(
        "rev-parse", "main", cwd=remote
    )
    parents = _git("rev-list", "--parents", "-n", "1", "main", cwd=remote).split()
    seed = _git("rev-list", "--max-parents=0", "main", cwd=remote).split()
    assert parents[1:] == seed


def test_a_second_run_for_the_tag_reuses_its_release_and_uploads_nothing(
    run, tmp_path, remote
):
    cnb = FakeCnb()
    dist = _dist(tmp_path)
    run(cnb, dist)
    head = _git("rev-parse", "main", cwd=remote)
    cnb.calls.clear()

    run(cnb, dist)

    assert cnb.changes() == []
    assert _git("rev-parse", "main", cwd=remote) == head


def test_a_run_again_uploads_only_what_the_release_lacks(run, tmp_path):
    cnb = FakeCnb()
    dist = _dist(tmp_path)
    held = dist / "neutrino-hub_9.9.9_amd64.deb"
    cnb.add_release(TAG, [(held.name, held.stat().st_size), ("install.sh", 1)])

    run(cnb, dist)

    uploads = [call for call in cnb.changes() if call[1].endswith("asset-upload-url")]
    assert len(uploads) == len(list(dist.iterdir())) - 1
    assert ("POST", "") not in cnb.changes()
    assert cnb.held(TAG)["install.sh"] == (dist / "install.sh").stat().st_size


def test_a_dry_run_changes_nothing_and_pushes_nothing(run, tmp_path, remote):
    cnb = FakeCnb()
    head = _git("rev-parse", "main", cwd=remote)

    run(cnb, _dist(tmp_path), is_dry_run=True)

    assert cnb.changes() == []
    assert _git("rev-parse", "main", cwd=remote) == head
    assert _git("tag", cwd=remote) == ""


def test_a_latest_json_naming_another_tag_stops_before_anything(run, tmp_path):
    cnb = FakeCnb()

    with pytest.raises(SystemExit) as refused:
        run(cnb, _dist(tmp_path, latest_tag="v9.9.8"))

    assert "latest.json names" in str(refused.value)
    assert cnb.calls == []


@pytest.mark.parametrize(
    "change, said",
    [
        ("missing", "the release holds no cc-switch-cli-v5.10.4-darwin-x64.tar.gz"),
        ("tampered", "cc-switch-cli-v5.10.4-darwin-x64.tar.gz hashes to "),
        ("licence", "the release holds no cc-switch-cli-v5.10.4-LICENSE.txt"),
    ],
)
def test_a_release_without_the_pinned_cc_switch_files_is_refused_before_anything(
    run, tmp_path, change, said
):
    cnb = FakeCnb()
    dist = _dist(tmp_path)
    if change == "missing":
        (dist / "cc-switch-cli-v5.10.4-darwin-x64.tar.gz").unlink()
    elif change == "tampered":
        (dist / "cc-switch-cli-v5.10.4-darwin-x64.tar.gz").write_bytes(b"changed")
    else:
        (dist / CC_SWITCH_LICENSE).unlink()

    with pytest.raises(SystemExit) as refused:
        run(cnb, dist)

    assert said in str(refused.value)
    assert cnb.calls == []


def test_a_refusal_names_the_call_and_never_the_token(publish_cn):
    def send(method, url, body, headers):
        return 403, f"bad token {TOKEN}".encode()

    client = publish_cn.CnbReleaseClient(
        token=TOKEN, api=API, repository=REPOSITORY, send=send
    )

    with pytest.raises(SystemExit) as refused:
        client.create_release(TAG, "")

    message = str(refused.value)
    assert "403" in message and f"/{REPOSITORY}/-/releases" in message
    assert TOKEN not in message


def test_the_push_carries_the_token_in_the_environment_alone(publish_cn):
    remote = publish_cn.GitRemote("https://cnb.invalid/iffi-X/neutrino.git", TOKEN)

    environment = remote._environment
    assert environment["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert TOKEN not in environment["GIT_CONFIG_VALUE_0"]
    credential = environment["GIT_CONFIG_VALUE_0"].rsplit(" ", 1)[1]
    import base64

    assert base64.b64decode(credential).decode() == f"cnb:{TOKEN}"


def test_a_pre_release_is_published_on_github_alone(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PUBLISH), "--tag", "v9.9.9-rc1", "--dist", str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0
    assert (
        result.stdout.strip()
        == "v9.9.9-rc1 is a pre-release, published on GitHub alone"
    )


def test_a_publish_needs_the_token(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PUBLISH), "--tag", TAG, "--dist", str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "CNB_TOKEN is needed to publish"


def test_an_upload_streams_its_file_and_waits_longer_than_a_plain_call(
    publish_cn, monkeypatch, tmp_path
):
    seen = []

    class Reply:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(request, timeout):
        seen.append((timeout, request.data.read() if request.data else None))
        return Reply()

    monkeypatch.setattr(publish_cn.urllib.request, "urlopen", urlopen)
    package = tmp_path / "package.deb"
    package.write_bytes(b"package bytes")

    publish_cn._send_with_urllib("PUT", "https://uploads.invalid/x", package, {})
    publish_cn._send_with_urllib("GET", "https://example.invalid/x", None, {})

    assert seen == [
        (publish_cn.PUBLISH_UPLOAD_TIMEOUT_S, b"package bytes"),
        (publish_cn.PUBLISH_REQUEST_TIMEOUT_S, None),
    ]
