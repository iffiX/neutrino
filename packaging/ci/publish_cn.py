"""Publish a release to CNB, the second release site, from what the release
workflow built.

    python3 packaging/ci/publish_cn.py --tag v0.6.0 --notes-file notes.md
    python3 packaging/ci/publish_cn.py --tag v0.6.0 --dist dist --dry-run

Runs on: Linux with git and, unless ``--dist`` names the files, the ``gh``
command with ``GH_TOKEN`` set. ``CNB_TOKEN`` is a CNB access token with the
repository's code and release scopes.

A tag with a suffix is a pre-release, published on GitHub alone, and the
script stops before it reads anything. Otherwise, in order: the workflow
artifact ``release_dist`` of the latest successful run of ``release.yml``
for the tag is downloaded; ``latest.json`` is checked to name the tag and
the pinned cc-switch files against their pins; the mainland source tree,
without ``third_party/``, and ``latest.json`` are committed as one commit on
CNB's ``main`` and pushed with the tag on it, unless CNB already holds the
tag; the tag's release is created, or the one it already has is reused; and
each file the release does not already hold under the same name and size is
uploaded. ``--dry-run`` does everything but the push and the requests that
change CNB.

Not pure: runs gh and git, and changes the repository on CNB.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cc_switch_assets  # noqa: E402
from shared.constants import (  # noqa: E402
    PACKAGING_CNB_API,
    PACKAGING_CNB_GIT_URL,
    PACKAGING_CNB_REPOSITORY,
    PACKAGING_LATEST_FILE,
)

# The workflow artifact the release workflow leaves the release's files in.
PUBLISH_ARTIFACT = "release_dist"
PUBLISH_WORKFLOW = "release.yml"
# The name the mainland source tree's archive ends with, and the directory
# of it that stays off the repository.
PUBLISH_SOURCE_SUFFIX = "-cn-source.tar.xz"
PUBLISH_THIRD_PARTY_DIR = "third_party"
# The branch the tree is committed on, and the author of its commit.
PUBLISH_BRANCH = "main"
PUBLISH_AUTHOR = ("Neutrino release", "release@neutrino.invalid")
# The account name CNB's git takes beside a token.
PUBLISH_GIT_USER = "cnb"
# The media type every CNB API call names.
PUBLISH_API_ACCEPT = "application/vnd.cnb.api+json"
PUBLISH_REQUEST_TIMEOUT_S = 600
# An upload carries a whole package; it ends when the file is up, however
# slowly the runner reaches CNB.
PUBLISH_UPLOAD_TIMEOUT_S = 3600


class CnbReleaseClient:
    """The few release calls of CNB's API the publish makes."""

    def __init__(
        self,
        *,
        token: str,
        api: str = PACKAGING_CNB_API,
        repository: str = PACKAGING_CNB_REPOSITORY,
        send=None,
    ):
        """Bind the client to one repository.

        Args:
            token: The access token every API call carries.
            api: The API's base address.
            repository: ``<owner>/<name>``.
            send: What carries one request, ``(method, url, body, headers)``
                to ``(status, bytes)``, the body bytes, a file to stream or
                None; urllib when not given.
        """
        self._token = token
        self._api = api.rstrip("/")
        self._base = f"{self._api}/{repository}/-/releases"
        self._send = send or _send_with_urllib

    def release_for_tag(self, tag: str) -> "dict | None":
        """The release a tag has, with the files it holds, or None.

        Args:
            tag: The tag.

        Returns:
            The release, ``assets`` among its keys, or None for a tag that
            has none.

        Raises:
            SystemExit: When CNB refuses the call.
        """
        found = self._call("GET", f"{self._base}/tags/{urllib.parse.quote(tag)}")
        if isinstance(found, dict) and found.get("id"):
            return found
        return None

    def create_release(self, tag: str, notes: str) -> dict:
        """Create the release of a tag CNB already holds.

        Args:
            tag: The tag, which also names the release.
            notes: The release's body.

        Returns:
            The release CNB made.

        Raises:
            SystemExit: When CNB refuses the call.
        """
        fields = {
            "tag_name": tag,
            "name": tag,
            "body": notes,
            "target_commitish": PUBLISH_BRANCH,
            "draft": False,
            "prerelease": False,
            "make_latest": "true",
        }
        return self._call("POST", self._base, fields=fields)

    def upload_asset(self, release_id: str, path: Path) -> None:
        """Upload one file to a release under its own name, replacing one of
        the same name.

        Args:
            release_id: The release.
            path: The file.

        Raises:
            SystemExit: When CNB refuses a step of the upload.
        """
        target = self._call(
            "POST",
            f"{self._base}/{release_id}/asset-upload-url",
            fields={
                "asset_name": path.name,
                "size": path.stat().st_size,
                "overwrite": True,
                "ttl": 0,
            },
        )
        status, answer = self._send(
            "PUT",
            str(target["upload_url"]),
            path,
            {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(path.stat().st_size),
            },
        )
        if not 200 <= status < 300:
            raise SystemExit(
                f"CNB answered {status} to the upload of {path.name}: "
                f"{answer.decode('utf-8', errors='replace')[:300]}"
            )
        verify = str(target["verify_url"])
        if verify.startswith("/"):
            verify = f"{self._api}{verify}"
        self._call("POST", verify)

    def _call(self, method: str, url: str, *, fields=None):
        """One API call, its JSON answer parsed.

        Raises:
            SystemExit: When CNB answers anything but success, a GET's 404
                aside; the message names the call and never the token.
        """
        headers = {
            "Accept": PUBLISH_API_ACCEPT,
            "Authorization": f"Bearer {self._token}",
        }
        body = None
        if fields is not None:
            body = json.dumps(fields).encode()
            headers["Content-Type"] = "application/json"
        status, answer = self._send(method, url, body, headers)
        if status == 404 and method == "GET":
            return None
        if not 200 <= status < 300:
            text = answer.decode("utf-8", errors="replace").replace(self._token, "***")
            path = urllib.parse.urlparse(url).path
            raise SystemExit(f"CNB answered {status} to {method} {path}: {text[:300]}")
        if not answer.strip():
            return None
        return json.loads(answer)


def main() -> int:
    """Publish the release to CNB.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="the tag to publish, v<version>")
    parser.add_argument("--notes-file", default="", help="the release notes")
    parser.add_argument(
        "--dist",
        default="",
        help="a directory holding the files; downloaded when empty",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="everything but the push and the requests that change CNB",
    )
    arguments = parser.parse_args()
    if "-" in arguments.tag:
        print(f"{arguments.tag} is a pre-release, published on GitHub alone")
        return 0
    token = os.environ.get("CNB_TOKEN", "")
    if not token:
        raise SystemExit("CNB_TOKEN is needed to publish")
    notes = (
        Path(arguments.notes_file).read_text(encoding="utf-8")
        if arguments.notes_file
        else ""
    )
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        dist = Path(arguments.dist) if arguments.dist else download(arguments.tag, work)
        publish(
            tag=arguments.tag,
            notes=notes,
            files=release_files(dist),
            work=work,
            client=CnbReleaseClient(token=token),
            git_url=PACKAGING_CNB_GIT_URL,
            git_token=token,
            is_dry_run=arguments.dry_run,
        )
    return 0


def publish(
    *,
    tag: str,
    notes: str,
    files: list,
    work: Path,
    client: CnbReleaseClient,
    git_url: str,
    git_token: str,
    is_dry_run: bool,
) -> None:
    """Publish the release to CNB, every check before the first change.

    Args:
        tag: The tag, ``v<version>``.
        notes: The release's body.
        files: Every file of the release.
        work: A directory to work in.
        client: CNB's API.
        git_url: The repository the tree is pushed to.
        git_token: The token the push carries.
        is_dry_run: Whether to stop short of the push and every request
            that changes CNB.

    Raises:
        SystemExit: When ``latest.json`` names another tag, a cc-switch file
            is missing or not its pin, git fails, or CNB refuses a call.
    """
    latest = check_latest(files, tag)
    check_cc_switch(files)
    tree, stamp = unpack_tree(files, work)
    (tree / PACKAGING_LATEST_FILE).write_bytes(latest.read_bytes())

    git = GitRemote(git_url, git_token)
    heads = git.heads(tree, tag)
    if f"refs/tags/{tag}" in heads:
        print(f"CNB already holds {tag}; nothing is pushed")
    elif is_dry_run:
        print(f"would commit the tree on {PUBLISH_BRANCH} and push it tagged {tag}")
    else:
        git.commit_and_push(
            tree, tag, stamp, has_branch=f"refs/heads/{PUBLISH_BRANCH}" in heads
        )

    release = client.release_for_tag(tag)
    if release is None:
        if is_dry_run:
            print(f"would create the release {tag} and upload {len(files)} files")
            return
        release = client.create_release(tag, notes)
    held = {
        str(asset.get("name")): int(asset.get("size", -1))
        for asset in release.get("assets") or []
    }
    for path in files:
        if held.get(path.name) == path.stat().st_size:
            continue
        print(f"  uploading {path.name}")
        if not is_dry_run:
            client.upload_asset(str(release["id"]), path)
    print(f"published {tag} on CNB")


def release_files(dist: Path) -> list:
    """The files a directory holds for the release, by name.

    Args:
        dist: The directory.

    Returns:
        Their paths, sorted.

    Raises:
        SystemExit: When it is no directory or holds no mainland source tree.
    """
    if not dist.is_dir():
        raise SystemExit(f"{dist} is not a directory of release files")
    files = sorted(path for path in dist.iterdir() if path.is_file())
    if not any(path.name.endswith(PUBLISH_SOURCE_SUFFIX) for path in files):
        raise SystemExit(f"{dist} holds no *{PUBLISH_SOURCE_SUFFIX}")
    return files


def check_latest(files: list, tag: str) -> Path:
    """The release's ``latest.json``, checked to name the tag.

    Args:
        files: The release's files.
        tag: The tag being published.

    Returns:
        Its path.

    Raises:
        SystemExit: When the release holds none or it names another tag.
    """
    held = {path.name: path for path in files}
    if PACKAGING_LATEST_FILE not in held:
        raise SystemExit(f"the release holds no {PACKAGING_LATEST_FILE}")
    try:
        named = json.loads(held[PACKAGING_LATEST_FILE].read_text(encoding="utf-8"))
    except ValueError as error:
        raise SystemExit(f"{PACKAGING_LATEST_FILE} is no JSON: {error}") from error
    if not isinstance(named, dict) or named.get("tag") != tag:
        raise SystemExit(f"{PACKAGING_LATEST_FILE} names {named!r}, not {tag}")
    return held[PACKAGING_LATEST_FILE]


def check_cc_switch(files: list) -> None:
    """Check that the release holds every pinned cc-switch file, as its pin
    says, and the licence beside them.

    Args:
        files: The release's files.

    Raises:
        SystemExit: Naming the first file missing or not its pin.
    """
    held = {path.name: path for path in files}
    for name, (_url, digest) in cc_switch_assets.release_files().items():
        if name not in held:
            raise SystemExit(f"the release holds no {name}")
        found = hashlib.sha256(held[name].read_bytes()).hexdigest()
        if found != digest:
            raise SystemExit(f"{name} hashes to {found}, not the pinned {digest}")
    if cc_switch_assets.license_name() not in held:
        raise SystemExit(f"the release holds no {cc_switch_assets.license_name()}")


def unpack_tree(files: list, work: Path) -> tuple:
    """Unpack the mainland source tree as it is committed, without
    third_party.

    Args:
        files: The release's files, one of them the tree's archive.
        work: A directory to unpack it in.

    Returns:
        ``(tree, time)``: the unpacked tree, and the time the archive gives
        its top directory, in seconds.

    Raises:
        SystemExit: When the archive does not hold one tree.
    """
    (archive,) = [path for path in files if path.name.endswith(PUBLISH_SOURCE_SUFFIX)]
    target = work / "tree"
    target.mkdir()
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        roots = {member.name.split("/", 1)[0] for member in members}
        if len(roots) != 1:
            raise SystemExit(f"{archive.name} does not hold one tree")
        kept = []
        stamp = 0
        for member in members:
            parts = member.name.split("/")
            if len(parts) > 1 and parts[1] == PUBLISH_THIRD_PARTY_DIR:
                continue
            if len(parts) == 1:
                stamp = member.mtime
                continue
            member.name = "/".join(parts[1:])
            kept.append(member)
        bundle.extractall(target, members=kept, filter="data")
    return target, int(stamp)


class GitRemote:
    """The repository on CNB, reached over HTTPS with the token."""

    def __init__(self, url: str, token: str):
        """Bind to one repository.

        Args:
            url: Its address.
            token: The token, sent as a header git reads from the
                environment and never on a command line.
        """
        self._url = url
        credential = base64.b64encode(f"{PUBLISH_GIT_USER}:{token}".encode()).decode()
        self._environment = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
        }

    def heads(self, directory: Path, tag: str) -> set:
        """Which of the branch and the tag the repository holds.

        Args:
            directory: Where git runs.
            tag: The tag.

        Returns:
            The refs among ``refs/heads/main`` and ``refs/tags/<tag>`` it
            holds.

        Raises:
            SystemExit: When the repository cannot be read.
        """
        listed = self._git(
            [
                "git",
                "ls-remote",
                self._url,
                f"refs/heads/{PUBLISH_BRANCH}",
                f"refs/tags/{tag}",
            ],
            directory,
        )
        return {line.split()[1] for line in listed.splitlines() if line.strip()}

    def commit_and_push(
        self, tree: Path, tag: str, stamp: int, *, has_branch: bool
    ) -> None:
        """Commit the tree on the repository's branch and push it tagged.

        Args:
            tree: The tree to commit, ``latest.json`` in it.
            tag: The tag to put on the commit.
            stamp: The commit's time, in seconds.
            has_branch: Whether the repository's branch exists, which the
                commit then follows.

        Raises:
            SystemExit: When git fails, a branch moved since it was read
                among the reasons.
        """
        date = f"{stamp} +0000"
        name, email = PUBLISH_AUTHOR
        environment = {
            **self._environment,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        self._git(["git", "init", "--quiet", "--initial-branch", PUBLISH_BRANCH], tree)
        if has_branch:
            self._git(
                [
                    "git",
                    "fetch",
                    "--quiet",
                    "--depth",
                    "1",
                    self._url,
                    f"refs/heads/{PUBLISH_BRANCH}",
                ],
                tree,
            )
            self._git(
                ["git", "update-ref", f"refs/heads/{PUBLISH_BRANCH}", "FETCH_HEAD"],
                tree,
            )
        for command in (
            ["git", "add", "--all"],
            [
                "git",
                "commit",
                "--quiet",
                "--no-gpg-sign",
                "--message",
                f"Neutrino {tag}",
            ],
            ["git", "tag", tag],
            [
                "git",
                "push",
                "--atomic",
                self._url,
                f"HEAD:refs/heads/{PUBLISH_BRANCH}",
                f"refs/tags/{tag}:refs/tags/{tag}",
            ],
        ):
            self._git(command, tree, environment)

    def _git(self, command: list, directory: Path, environment=None) -> str:
        """Run one git command.

        Returns:
            What it printed.

        Raises:
            SystemExit: When it fails.
        """
        result = subprocess.run(
            command,
            cwd=directory,
            env=environment or self._environment,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                f"{' '.join(command[:2])} failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        return result.stdout


def download(tag: str, work: Path) -> Path:
    """Download the files the release workflow built for a tag.

    Args:
        tag: The tag whose run to take them from.
        work: A directory to download into.

    Returns:
        The directory holding them.

    Raises:
        SystemExit: When no successful run built the tag, or gh fails.
    """
    listed = _gh(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            PUBLISH_WORKFLOW,
            "--branch",
            tag,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ]
    )
    runs = json.loads(listed or "[]")
    if not runs:
        raise SystemExit(f"no successful run of {PUBLISH_WORKFLOW} built {tag}")
    dist = work / "dist"
    _gh(
        [
            "gh",
            "run",
            "download",
            str(runs[0]["databaseId"]),
            "--name",
            PUBLISH_ARTIFACT,
            "--dir",
            str(dist),
        ]
    )
    return dist


def _send_with_urllib(method: str, url: str, body, headers: dict) -> tuple:
    """Carry one request with urllib; an upload streams its file and waits
    ``PUBLISH_UPLOAD_TIMEOUT_S``.

    Returns:
        ``(status, body)``, an error status included.
    """
    is_upload = isinstance(body, Path)
    timeout = PUBLISH_UPLOAD_TIMEOUT_S if is_upload else PUBLISH_REQUEST_TIMEOUT_S
    try:
        if is_upload:
            with body.open("rb") as stream:
                request = urllib.request.Request(
                    url, data=stream, headers=headers, method=method
                )
                with urllib.request.urlopen(request, timeout=timeout) as reply:
                    return reply.status, reply.read()
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read()


def _gh(command: list) -> str:
    """Run one gh command.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed: {(result.stderr or result.stdout).strip()}"
        )
    return result.stdout


if __name__ == "__main__":
    sys.exit(main())
