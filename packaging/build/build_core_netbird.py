"""NetBird's Android library, built from its pinned source for the phone app.

    python3 packaging/build/build_core_netbird.py

Runs on: Linux or macOS. With the library already in the cores cache it
needs nothing else; building it needs Go, ``gomobile`` and ``gobind`` on the
path (``gomobile init`` done), and ``ANDROID_HOME`` and ``ANDROID_NDK_HOME``
set.

NetBird publishes no library for phones, so the app carries one compiled
here: ``gomobile bind`` over ``client/android`` of the pinned release, for
the two machines the app ships (arm64-v8a for phones, x86_64 for the
emulator). The source archive is checked against its SHA-256 and the commit
its header names before anything is built. The result is cached under
``~/.cache/neutrino/cores/netbird-<commit>-arm64-v8a+x86_64/`` and copied to
``client/android/app/libs/netbird.aar``. ``--cache-key`` prints that cache
name and builds nothing.

Not pure: downloads, unpacks and compiles.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cores_cache  # noqa: E402

# --- the pinned source ---
# The same archive build_sources.py puts in the release's third_party/.
NETBIRD_MOBILE_TAG = "v0.78.1"
NETBIRD_MOBILE_COMMIT = "23a1487c26c5f00353c046bc818069189650dbfb"  # scan: allow
NETBIRD_MOBILE_ARCHIVE_URL = (
    "https://github.com/netbirdio/netbird/archive/refs/tags/v0.78.1.tar.gz"
)
NETBIRD_MOBILE_ARCHIVE_SHA256 = (
    "2adde8bbd77ea595b5f50174be10574466f1c07fc9fbf827024245aec2f4dabc"  # scan: allow
)

# --- the build ---
# The Go package bound, the Java package its classes land in, and the
# machines built for, as gomobile names them.
NETBIRD_MOBILE_PACKAGE = "./client/android"
NETBIRD_MOBILE_JAVA_PACKAGE = "io.netbird.gomobile"
NETBIRD_MOBILE_TARGETS = "android/arm64,android/amd64"
NETBIRD_MOBILE_ANDROID_API = "26"
# Where WireGuard's control sockets live inside the app's own directory.
NETBIRD_MOBILE_SOCKET_DIR = "/data/data/io.github.iffix.neutrino/cache/wireguard"
# The libraries load on phones with 16 KB pages.
NETBIRD_MOBILE_LDFLAGS = (
    "-checklinkname=0 -extldflags=-Wl,-z,max-page-size=16384 "
    f"-X golang.zx2c4.com/wireguard/ipc.socketDirectory={NETBIRD_MOBILE_SOCKET_DIR} "
    f"-X github.com/netbirdio/netbird/version.version={NETBIRD_MOBILE_TAG[1:]}"
)
# The Go release the source's go.mod names as its toolchain; its exec
# workaround reaches into the standard library by linkname.
NETBIRD_MOBILE_GO_TOOLCHAIN = "go1.26.7"
NETBIRD_MOBILE_LIBRARY = "netbird.aar"
# The one library holds both machines, so it is cached under both.
NETBIRD_MOBILE_ABIS = "arm64-v8a+x86_64"
NETBIRD_MOBILE_OUTPUT = REPO_ROOT / "client" / "android" / "app" / "libs"


def fetch_source(work_dir: Path) -> Path:
    """Download the pinned archive, check it, and unpack it.

    Args:
        work_dir: Where the archive and the tree go.

    Returns:
        The root of the unpacked tree.

    Raises:
        SystemExit: When the archive is not the one pinned.
    """
    archive = work_dir / "netbird.tar.gz"
    if not archive.exists():
        print(f"downloading {NETBIRD_MOBILE_ARCHIVE_URL}")
        with urllib.request.urlopen(NETBIRD_MOBILE_ARCHIVE_URL) as response:
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != NETBIRD_MOBILE_ARCHIVE_SHA256:
        archive.unlink()
        raise SystemExit(f"netbird archive sha256 {digest} is not the pinned one")
    with tarfile.open(archive) as tar:
        commit = tar.pax_headers.get("comment", "")
        if commit != NETBIRD_MOBILE_COMMIT:
            raise SystemExit(f"netbird archive names commit {commit!r}")
        root = work_dir / tar.getmembers()[0].name.split("/")[0]
        if not root.exists():
            tar.extractall(work_dir, filter="fully_trusted")
    return root


def bind(source: Path, output: Path) -> None:
    """Run ``gomobile bind`` over the Android package into one ``.aar``.

    Args:
        source: The unpacked tree.
        output: The ``.aar`` to write.

    Raises:
        SystemExit: When the bind fails.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "gomobile",
        "bind",
        "-target",
        NETBIRD_MOBILE_TARGETS,
        "-androidapi",
        NETBIRD_MOBILE_ANDROID_API,
        "-javapkg",
        NETBIRD_MOBILE_JAVA_PACKAGE,
        "-trimpath",
        "-ldflags",
        NETBIRD_MOBILE_LDFLAGS,
        "-o",
        str(output),
        NETBIRD_MOBILE_PACKAGE,
    ]
    print(" ".join(command))
    environment = dict(os.environ, GOTOOLCHAIN=NETBIRD_MOBILE_GO_TOOLCHAIN)
    result = subprocess.run(command, cwd=source, env=environment, check=False)
    if result.returncode != 0:
        raise SystemExit(f"gomobile bind exited {result.returncode}")


def main() -> int:
    """Build the library, or take it from the cache, and copy it into the app.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default=str(NETBIRD_MOBILE_OUTPUT),
        help="the directory the .aar is copied to",
    )
    parser.add_argument(
        "--work-dir", default="", help="where the source is unpacked; a temporary one"
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="build even when the cache has it"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cache name and stop"
    )
    arguments = parser.parse_args()
    if arguments.cache_key:
        print(
            cores_cache.cache_key("netbird", NETBIRD_MOBILE_COMMIT, NETBIRD_MOBILE_ABIS)
        )
        return 0
    cached = cores_cache.cache_dir("netbird", NETBIRD_MOBILE_COMMIT, NETBIRD_MOBILE_ABIS)
    if arguments.rebuild or not cores_cache.is_cached(cached):
        _check_tools()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="build_core_netbird_") as scratch:
            work_dir = Path(arguments.work_dir or scratch)
            work_dir.mkdir(parents=True, exist_ok=True)
            source = fetch_source(work_dir)
            built = Path(scratch) / "built"
            bind(source, built / NETBIRD_MOBILE_LIBRARY)
            cores_cache.store(built, cached)
        print(
            f"netbird {NETBIRD_MOBILE_TAG} ({NETBIRD_MOBILE_COMMIT[:12]}) "
            f"built in {time.monotonic() - started:.0f}s: {cached}"
        )
    else:
        print(f"netbird {NETBIRD_MOBILE_TAG} from the cache: {cached}")
    cores_cache.install(cached, Path(arguments.output).resolve())
    return 0


def _check_tools() -> None:
    """Refuse to build without the tools the bind runs.

    Raises:
        SystemExit: When a tool or an Android variable is missing.
    """
    for tool in ("go", "gomobile", "gobind"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed to build NetBird and is not on the path")
    for variable in ("ANDROID_HOME", "ANDROID_NDK_HOME"):
        if not os.environ.get(variable):
            raise SystemExit(f"{variable} is needed to build NetBird and is not set")


if __name__ == "__main__":
    sys.exit(main())
