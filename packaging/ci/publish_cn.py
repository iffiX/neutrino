"""Publish the mainland release on Gitee from what the release workflow built.

    python3 packaging/ci/publish_cn.py --tag v0.5.0 --notes-file notes.md
    python3 packaging/ci/publish_cn.py --check-only --dist dist_cn

Runs on: Linux with git, ssh and, unless ``--dist`` names the files, the
``gh`` command with ``GH_TOKEN`` set. ``GITEE_TOKEN`` is a Gitee personal
access token with the ``projects`` scope and ``GITEE_SSH_KEY`` the private
key the push uses; ``--check-only`` needs neither.

In order: the workflow artifact ``release_dist_cn`` of the latest
successful run of ``release.yml`` for the tag is downloaded; every file is
checked against Gitee's limits, and the pinned cc-switch release files the
mainland hubs fetch from the release against their pins, before anything
changes on Gitee; the
mainland source tree, without ``third_party/``, is committed as one commit
with no parent and force-pushed to ``main`` with the tag on it; the
attachments of every earlier release are deleted; the release for the tag is
created, or the one it already has is reused; and each file the release
does not already hold under the same name and size is uploaded.
``--check-only`` stops after the checks, and ``--dry-run`` does everything
but the push and the requests that change Gitee.

Not pure: runs gh, git and ssh, and changes the repository on Gitee.
"""

import argparse
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
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cc_switch_assets  # noqa: E402
from shared.constants import (  # noqa: E402
    PACKAGING_GITEE_API,
    PACKAGING_GITEE_ATTACHMENT_BYTES_MAX,
    PACKAGING_GITEE_ATTACHMENTS_BYTES_MAX,
    PACKAGING_GITEE_FILE_BYTES_MAX,
    PACKAGING_GITEE_PUSH_URL,
    PACKAGING_GITEE_REPOSITORY,
    PACKAGING_GITEE_REPOSITORY_BYTES_MAX,
    PACKAGING_GITEE_SSH_HOST_KEY,
)

# The workflow artifact the release workflow leaves the mainland files in.
PUBLISH_ARTIFACT = "release_dist_cn"
PUBLISH_WORKFLOW = "release.yml"
# The name the mainland source tree's archive ends with, and the directory
# of it that stays off Gitee.
PUBLISH_SOURCE_SUFFIX = "-cn-source.tar.gz"
PUBLISH_THIRD_PARTY_DIR = "third_party"
# The branch the tree is pushed to, and the author of its one commit.
PUBLISH_BRANCH = "main"
PUBLISH_AUTHOR = ("Neutrino release", "release@neutrino.invalid")
# How many entries one page of a Gitee listing holds.
PUBLISH_PAGE_SIZE = 100
PUBLISH_REQUEST_TIMEOUT_S = 600


class GiteeReleaseClient:
    """The few release calls of Gitee's v5 API the publish makes."""

    def __init__(
        self,
        *,
        token: str,
        api: str = PACKAGING_GITEE_API,
        repository: str = PACKAGING_GITEE_REPOSITORY,
        send=None,
    ):
        """Bind the client to one repository.

        Args:
            token: The personal access token every call carries.
            api: The API's base address.
            repository: ``<owner>/<name>``.
            send: What carries one request, ``(method, url, body, headers)``
                to ``(status, bytes)``; urllib when not given.
        """
        self._token = token
        self._base = f"{api}/repos/{repository}"
        self._send = send or _send_with_urllib

    def releases(self) -> list:
        """Every release of the repository.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        return self._pages("/releases")

    def release_for_tag(self, tag: str) -> "dict | None":
        """The release a tag has, or None.

        Args:
            tag: The tag.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        found = self._call("GET", f"/releases/tags/{urllib.parse.quote(tag)}")
        if isinstance(found, dict) and found.get("id"):
            return found
        return None

    def create_release(self, tag: str, notes: str) -> dict:
        """Create the release for a tag.

        Args:
            tag: The tag, which also names the release.
            notes: The release's body.

        Returns:
            The release Gitee made.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        fields = {
            "tag_name": tag,
            "name": tag,
            "body": notes,
            "target_commitish": PUBLISH_BRANCH,
            "prerelease": "false",
        }
        return self._call("POST", "/releases", fields=fields)

    def attachments(self, release_id: int) -> list:
        """The files attached to a release.

        Args:
            release_id: The release.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        return self._pages(f"/releases/{release_id}/attach_files")

    def delete_attachment(self, release_id: int, file_id: int) -> None:
        """Delete one attached file.

        Args:
            release_id: The release.
            file_id: The file.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        self._call("DELETE", f"/releases/{release_id}/attach_files/{file_id}")

    def upload_attachment(self, release_id: int, path: Path) -> dict:
        """Attach one file to a release.

        Args:
            release_id: The release.
            path: The file.

        Returns:
            What Gitee says it holds.

        Raises:
            SystemExit: When Gitee refuses the call.
        """
        return self._call("POST", f"/releases/{release_id}/attach_files", upload=path)

    def _pages(self, path: str) -> list:
        """Every entry of a paged listing."""
        entries = []
        page = 1
        while True:
            found = self._call(
                "GET", path, query={"page": page, "per_page": PUBLISH_PAGE_SIZE}
            )
            entries += found or []
            if not found or len(found) < PUBLISH_PAGE_SIZE:
                return entries
            page += 1

    def _call(self, method: str, path: str, *, query=None, fields=None, upload=None):
        """One API call, its JSON answer parsed.

        Raises:
            SystemExit: When Gitee answers anything but success; the message
                names the call and never the token.
        """
        parameters = dict(query or {})
        headers = {"Accept": "application/json"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode(
                {"access_token": self._token, **fields}
            ).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif upload is not None:
            body, headers["Content-Type"] = _multipart(
                {"access_token": self._token}, "file", upload
            )
        else:
            parameters["access_token"] = self._token
        url = f"{self._base}{path}"
        if parameters:
            url += "?" + urllib.parse.urlencode(parameters)
        status, answer = self._send(method, url, body, headers)
        if status == 404 and method == "GET":
            return None
        if not 200 <= status < 300:
            text = answer.decode("utf-8", errors="replace").replace(self._token, "***")
            raise SystemExit(
                f"Gitee answered {status} to {method} {path}: {text[:300]}"
            )
        if not answer.strip():
            return None
        return json.loads(answer)


def main() -> int:
    """Publish, or only check, the mainland release.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default="", help="the tag to publish, v<version>")
    parser.add_argument("--notes-file", default="", help="the release notes")
    parser.add_argument(
        "--dist",
        default="",
        help="a directory holding the files; downloaded when empty",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="check the limits and stop"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="everything but the push and the requests that change Gitee",
    )
    arguments = parser.parse_args()
    if arguments.check_only:
        if not arguments.dist:
            raise SystemExit("--check-only checks the files --dist names")
        files = release_files(Path(arguments.dist))
        with tempfile.TemporaryDirectory() as workdir:
            tree, _stamp = unpack_tree(files, Path(workdir))
            check_limits(files, tree)
        check_cc_switch(files)
        print(f"{len(files)} files are within Gitee's limits")
        return 0

    if not arguments.tag:
        raise SystemExit("--tag names the release to publish")
    token = os.environ.get("GITEE_TOKEN", "")
    ssh_key = os.environ.get("GITEE_SSH_KEY", "")
    if not token or (not ssh_key and not arguments.dry_run):
        raise SystemExit("GITEE_TOKEN and GITEE_SSH_KEY are needed to publish")
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
            client=GiteeReleaseClient(token=token),
            ssh_key=ssh_key,
            is_dry_run=arguments.dry_run,
        )
    return 0


def publish(
    *,
    tag: str,
    notes: str,
    files: list,
    work: Path,
    client: GiteeReleaseClient,
    ssh_key: str,
    is_dry_run: bool,
) -> None:
    """Publish the mainland release, every check before the first change.

    Args:
        tag: The tag, ``v<version>``.
        notes: The release's body.
        files: Every file the release carries.
        work: A directory to work in.
        client: The Gitee API.
        ssh_key: The private key the push uses.
        is_dry_run: Whether to stop short of the push and every request
            that changes Gitee.

    Raises:
        SystemExit: When a file is over a limit, a cc-switch file is missing
            or not its pin, the push fails, or Gitee refuses a call.
    """
    tree, stamp = unpack_tree(files, work)
    check_limits(files, tree)
    check_cc_switch(files)
    commit_tree(tree, tag, stamp)
    if is_dry_run:
        print(f"would push the tree to {PUBLISH_BRANCH} and tag it {tag}")
    else:
        push_tree(tree, tag, ssh_key, work)

    for release in client.releases():
        if release.get("tag_name") == tag:
            continue
        for attached in client.attachments(release["id"]):
            print(f"  deleting {attached['name']} from {release.get('tag_name')}")
            if not is_dry_run:
                client.delete_attachment(release["id"], attached["id"])

    release = client.release_for_tag(tag)
    if release is None:
        if is_dry_run:
            print(f"would create the release {tag} and upload {len(files)} files")
            return
        release = client.create_release(tag, notes)
    held = {item["name"]: item for item in client.attachments(release["id"])}
    for path in files:
        attached = held.get(path.name)
        if (
            attached is not None
            and int(attached.get("size", -1)) == path.stat().st_size
        ):
            continue
        print(f"  uploading {path.name}")
        if is_dry_run:
            continue
        if attached is not None:
            client.delete_attachment(release["id"], attached["id"])
        client.upload_attachment(release["id"], path)
    print(f"published {tag} on Gitee")


def release_files(dist: Path) -> list:
    """The files a directory holds for the release, by name.

    Args:
        dist: The directory.

    Raises:
        SystemExit: When it holds no mainland source tree.
    """
    if not dist.is_dir():
        raise SystemExit(f"{dist} is not a directory of release files")
    files = sorted(path for path in dist.iterdir() if path.is_file())
    if not any(path.name.endswith(PUBLISH_SOURCE_SUFFIX) for path in files):
        raise SystemExit(f"{dist} holds no *{PUBLISH_SOURCE_SUFFIX}")
    return files


def check_cc_switch(files: list) -> None:
    """Check that the release carries every pinned cc-switch file, as its pin
    says, and the licence beside them.

    Args:
        files: The release's files.

    Raises:
        SystemExit: Naming the first file missing or not its pin.
    """
    held = {path.name: path for path in files}
    for name, (_url, digest) in cc_switch_assets.release_files().items():
        if name not in held:
            raise SystemExit(f"the release carries no {name}")
        found = hashlib.sha256(held[name].read_bytes()).hexdigest()
        if found != digest:
            raise SystemExit(f"{name} hashes to {found}, not the pinned {digest}")
    if cc_switch_assets.license_name() not in held:
        raise SystemExit(f"the release carries no {cc_switch_assets.license_name()}")


def check_limits(files: list, tree: Path) -> None:
    """Check every file against Gitee's limits.

    Args:
        files: The release's files.
        tree: The mainland source tree, unpacked as it is pushed.

    Raises:
        SystemExit: Naming the file, its size and the limit, for the first
            one over.
    """
    total = 0
    for path in files:
        size = path.stat().st_size
        total += size
        if size > PACKAGING_GITEE_ATTACHMENT_BYTES_MAX:
            raise SystemExit(
                f"{path.name} is {size} bytes, over Gitee's limit of "
                f"{PACKAGING_GITEE_ATTACHMENT_BYTES_MAX} bytes for one attachment"
            )
    if total > PACKAGING_GITEE_ATTACHMENTS_BYTES_MAX:
        raise SystemExit(
            f"the {len(files)} files are {total} bytes, over Gitee's limit of "
            f"{PACKAGING_GITEE_ATTACHMENTS_BYTES_MAX} bytes for all attachments"
        )
    total = 0
    for path in sorted(tree.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        total += size
        if size > PACKAGING_GITEE_FILE_BYTES_MAX:
            raise SystemExit(
                f"{path.relative_to(tree)} is {size} bytes, over Gitee's limit "
                f"of {PACKAGING_GITEE_FILE_BYTES_MAX} bytes for one file"
            )
    if total > PACKAGING_GITEE_REPOSITORY_BYTES_MAX:
        raise SystemExit(
            f"the mainland tree is {total} bytes, over Gitee's limit of "
            f"{PACKAGING_GITEE_REPOSITORY_BYTES_MAX} bytes for a repository"
        )


def unpack_tree(files: list, work: Path) -> tuple:
    """Unpack the mainland source tree as it is pushed, without third_party.

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
        (root,) = roots
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


def commit_tree(tree: Path, tag: str, stamp: int) -> None:
    """Make the tree one commit with no parent, tagged, at a fixed time.

    The same archive therefore makes the same commit on every run.

    Args:
        tree: The unpacked tree.
        tag: The tag to put on the commit.
        stamp: The commit's time, in seconds.

    Raises:
        SystemExit: When git fails.
    """
    date = f"{stamp} +0000"
    name, email = PUBLISH_AUTHOR
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    for command in (
        ["git", "init", "--quiet", "--initial-branch", PUBLISH_BRANCH],
        ["git", "add", "--all"],
        ["git", "commit", "--quiet", "--no-gpg-sign", "--message", f"Neutrino {tag}"],
        ["git", "tag", tag],
    ):
        _git(command, tree, environment)


def push_tree(tree: Path, tag: str, ssh_key: str, work: Path) -> None:
    """Force-push the commit to the branch and the tag, checking gitee.com's
    host key against the one pinned.

    Args:
        tree: The committed tree.
        tag: The tag on the commit.
        ssh_key: The private key.
        work: A directory for the key and the known hosts file.

    Raises:
        SystemExit: When the push fails, a changed host key among the reasons.
    """
    key = work / "gitee_key"
    key.write_text(ssh_key.strip() + "\n", encoding="utf-8")
    key.chmod(0o600)
    known_hosts = work / "known_hosts"
    known_hosts.write_text(PACKAGING_GITEE_SSH_HOST_KEY + "\n", encoding="utf-8")
    environment = {
        **os.environ,
        "GIT_SSH_COMMAND": (
            f"ssh -i {key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={known_hosts}"
        ),
    }
    _git(
        [
            "git",
            "push",
            "--force",
            PACKAGING_GITEE_PUSH_URL,
            f"HEAD:refs/heads/{PUBLISH_BRANCH}",
            f"refs/tags/{tag}:refs/tags/{tag}",
        ],
        tree,
        environment,
    )


def download(tag: str, work: Path) -> Path:
    """Download the mainland files the release workflow built for a tag.

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
    """Carry one request with urllib.

    Returns:
        ``(status, body)``, an error status included.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(
            request, timeout=PUBLISH_REQUEST_TIMEOUT_S
        ) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read()


def _multipart(fields: dict, name: str, path: Path) -> tuple:
    """A multipart form holding some fields and one file.

    Returns:
        ``(body, content type)``.
    """
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
        f'filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _git(command: list, tree: Path, environment: dict) -> None:
    """Run one git command in the tree.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(
        command, cwd=tree, env=environment, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:2])} failed: {(result.stderr or result.stdout).strip()}"
        )


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
