"""EasyTier's Android libraries, built from their pinned source for the phone app.

    python3 packaging/build/build_core_easytier.py

Runs on: Linux on x86-64, or any host that names its own ``PROTOC``. With the
libraries already in the cores cache it needs nothing else; building them
needs rustup, ``cargo-ndk``, ``patch``, ``ANDROID_NDK_HOME``, and a host
libclang for bindgen: the system's, or the directory ``LIBCLANG_PATH`` names.
``protoc`` is the pinned release below unless ``PROTOC`` names one. The
toolchain is the one upstream's ``rust-toolchain.toml`` names; its two Android
targets are added when missing.

EasyTier publishes no library for phones, so the app carries its
``easytier-android-jni`` binding compiled here with ``cargo ndk``, for the two
machines the app ships (arm64-v8a for phones, x86_64 for the emulator). The
source archive is checked against its SHA-256 and the commit its header names
before anything is built. ``build_core_easytier.patch`` beside this file is
then applied: it links the C interface (``easytier-ffi``) into the JNI
library, so the app loads one library, and adds the calls that start and stop
a console's web client. Each machine's library is cached under
``~/.cache/neutrino/cores/easytier-<commit>-<abi>-<recipe>/``, the recipe
being the digest of this file and the patch, and copied to
``client/android/app/src/main/jniLibs/<abi>/libeasytier_android_jni.so``.
``--cache-key`` prints the cache names and builds nothing.

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
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cores_cache  # noqa: E402

# --- the pinned source ---
# The same archive build_sources.py puts in the release's third_party/.
EASYTIER_MOBILE_TAG = "v2.6.4"
EASYTIER_MOBILE_COMMIT = "8428a89d2dabc94c97d370ec607c6ca142473626"  # scan: allow
EASYTIER_MOBILE_ARCHIVE_URL = (
    "https://github.com/EasyTier/EasyTier/archive/refs/tags/v2.6.4.tar.gz"
)
EASYTIER_MOBILE_ARCHIVE_SHA256 = (
    "352c0866da709415a837405a6ce4f51b8dfae27e5d5c1da1fb4d8f7338e46795"  # scan: allow
)

# The protobuf compiler the build scripts run on the host.
EASYTIER_MOBILE_PROTOC_URL = (
    "https://github.com/protocolbuffers/protobuf/releases/download/"
    "v36.2/protoc-36.2-linux-x86_64.zip"
)
EASYTIER_MOBILE_PROTOC_SHA256 = (
    "121f6c7afe1d4d0e3ea6aab9432038599250134cbf4474cb1167d2c7decd4278"  # scan: allow
)

# --- the build ---
# The two crates built, the machines built for as cargo-ndk names them with
# the Rust targets behind them, and the Android API the libraries link
# against.
EASYTIER_MOBILE_CRATE = "easytier-android-jni"
EASYTIER_MOBILE_ABIS = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
}
EASYTIER_MOBILE_ANDROID_API = "26"
EASYTIER_MOBILE_LIBRARY = "libeasytier_android_jni.so"
EASYTIER_MOBILE_PATCH = Path(__file__).resolve().parent / "build_core_easytier.patch"
EASYTIER_MOBILE_RECIPE = cores_cache.recipe(
    Path(__file__).resolve(), EASYTIER_MOBILE_PATCH
)
EASYTIER_MOBILE_OUTPUT = (
    REPO_ROOT / "client" / "android" / "app" / "src" / "main" / "jniLibs"
)


def fetch_source(work_dir: Path) -> Path:
    """Download the pinned archive, check it, and unpack it.

    Args:
        work_dir: Where the archive and the tree go.

    Returns:
        The root of the unpacked tree.

    Raises:
        SystemExit: When the archive is not the one pinned.
    """
    archive = work_dir / "easytier.tar.gz"
    if not archive.exists():
        print(f"downloading {EASYTIER_MOBILE_ARCHIVE_URL}")
        with urllib.request.urlopen(EASYTIER_MOBILE_ARCHIVE_URL) as response:
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != EASYTIER_MOBILE_ARCHIVE_SHA256:
        archive.unlink()
        raise SystemExit(f"easytier archive sha256 {digest} is not the pinned one")
    with tarfile.open(archive) as tar:
        commit = tar.pax_headers.get("comment", "")
        if commit != EASYTIER_MOBILE_COMMIT:
            raise SystemExit(f"easytier archive names commit {commit!r}")
        root = work_dir / tar.getmembers()[0].name.split("/")[0]
        if root.exists():
            shutil.rmtree(root)
        tar.extractall(work_dir, filter="fully_trusted")
    _run(["patch", "-p1", "--input", str(EASYTIER_MOBILE_PATCH)], root)
    return root


def fetch_protoc(work_dir: Path) -> str:
    """The protobuf compiler: ``PROTOC`` when set, else the pinned release.

    Args:
        work_dir: Where the release is unpacked.

    Returns:
        The path of the ``protoc`` binary.

    Raises:
        SystemExit: When the download is not the one pinned.
    """
    if os.environ.get("PROTOC"):
        return os.environ["PROTOC"]
    archive = work_dir / "protoc.zip"
    if not archive.exists():
        print(f"downloading {EASYTIER_MOBILE_PROTOC_URL}")
        with urllib.request.urlopen(EASYTIER_MOBILE_PROTOC_URL) as response:
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != EASYTIER_MOBILE_PROTOC_SHA256:
        archive.unlink()
        raise SystemExit(f"protoc sha256 {digest} is not the pinned one")
    target = work_dir / "protoc"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    binary = target / "bin" / "protoc"
    binary.chmod(0o755)
    return str(binary)


def build(source: Path, output: Path, protoc: str) -> None:
    """Compile both crates for every machine and copy the libraries out.

    Args:
        source: The unpacked tree.
        output: The ``jniLibs`` directory to fill, one directory per ABI.
        protoc: The protobuf compiler's path.

    Raises:
        SystemExit: When a build fails.
    """
    target_dir = source.parent / "target"
    environment = dict(os.environ, PROTOC=protoc, CARGO_TARGET_DIR=str(target_dir))
    _run(["rustup", "target", "add", *EASYTIER_MOBILE_ABIS.values()], source)
    command = ["cargo", "ndk"]
    for abi in EASYTIER_MOBILE_ABIS:
        command += ["-t", abi]
    command += ["--platform", EASYTIER_MOBILE_ANDROID_API, "build", "--release"]
    command += ["-p", EASYTIER_MOBILE_CRATE]
    _run(command, source, environment)
    for abi, target in EASYTIER_MOBILE_ABIS.items():
        destination = output / abi
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            target_dir / target / "release" / EASYTIER_MOBILE_LIBRARY, destination
        )


def _run(command: list, cwd: Path, environment: "dict | None" = None) -> None:
    """Run one build step in the source tree, failing the build on an error."""
    print(" ".join(command))
    result = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{command[0]} {command[1]} exited {result.returncode}")


def main() -> int:
    """Build the libraries, or take them from the cache, and copy them into the app.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default=str(EASYTIER_MOBILE_OUTPUT),
        help="the jniLibs directory to fill",
    )
    parser.add_argument(
        "--work-dir", default="", help="where the source is unpacked; a temporary one"
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="build even when the cache has them"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cache names and stop"
    )
    arguments = parser.parse_args()
    if arguments.cache_key:
        for abi in EASYTIER_MOBILE_ABIS:
            print(
                cores_cache.cache_key(
                    "easytier", EASYTIER_MOBILE_COMMIT, abi, EASYTIER_MOBILE_RECIPE
                )
            )
        return 0
    cached = {
        abi: cores_cache.cache_dir(
            "easytier", EASYTIER_MOBILE_COMMIT, abi, EASYTIER_MOBILE_RECIPE
        )
        for abi in EASYTIER_MOBILE_ABIS
    }
    if arguments.rebuild or not all(map(cores_cache.is_cached, cached.values())):
        _check_tools()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="build_core_easytier_") as scratch:
            work_dir = Path(arguments.work_dir or scratch)
            work_dir.mkdir(parents=True, exist_ok=True)
            source = fetch_source(work_dir)
            built = Path(scratch) / "built"
            build(source, built, fetch_protoc(work_dir))
            for abi, directory in cached.items():
                cores_cache.store(built / abi, directory)
        print(
            f"easytier {EASYTIER_MOBILE_TAG} ({EASYTIER_MOBILE_COMMIT[:12]}) "
            f"built in {time.monotonic() - started:.0f}s"
        )
    else:
        print(f"easytier {EASYTIER_MOBILE_TAG} from the cache")
    output = Path(arguments.output).resolve()
    for abi, directory in cached.items():
        cores_cache.install(directory, output / abi)
    return 0


def _check_tools() -> None:
    """Refuse to build without the tools the build runs.

    Raises:
        SystemExit: When a tool or ``ANDROID_NDK_HOME`` is missing.
    """
    for tool in ("rustup", "cargo", "cargo-ndk", "patch"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed to build EasyTier and is not on the path")
    if not os.environ.get("ANDROID_NDK_HOME"):
        raise SystemExit("ANDROID_NDK_HOME is needed to build EasyTier and is not set")


if __name__ == "__main__":
    sys.exit(main())
