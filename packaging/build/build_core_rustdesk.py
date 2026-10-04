"""RustDesk's Android library, built from its pinned source for the phone app.

    python3 packaging/build/build_core_rustdesk.py

Runs on: Linux on x86-64. With the libraries already in the cores cache it
needs nothing else; building them needs what the last paragraph names.

RustDesk publishes no library for a host without Flutter, so the app carries
the RustDesk crate compiled here with ``cargo ndk``, for the two machines the
app ships (arm64-v8a for phones, with MediaCodec's hardware H264 and H265
decoders; x86_64 for the emulator, without). The phone build leaves out
``hwcodec``: its FFmpeg software decoders come before MediaCodec in RustDesk's
decoder choice, so with both the hardware decoders would never be used. The source archive and its ``hbb_common`` submodule are
checked against their SHA-256 and the commits their headers name before
anything is built. ``build_core_rustdesk.patch`` beside this file is then applied:
it adds a small C interface (``src/native_ffi.rs``) behind a ``native``
feature, which also drops the Dart bridge the Flutter build generates. The
codec libraries are built with vcpkg at the commit RustDesk pins, with
RustDesk's own overlay ports, as ``flutter/build_android_deps.sh`` does. The
two libraries of each machine, ``librustdesk.so`` and the NDK's
``libc++_shared.so``, are cached under
``~/.cache/neutrino/cores/rustdesk-<commit>-<abi>-<recipe>/``, the recipe
being the digest of this file and the patch, and copied to
``client/android/app/src/main/jniLibs/<abi>/``. ``--cache-key`` prints the
cache names and builds nothing.

What building fetches and keeps between runs, the NDK, vcpkg and its
installed libraries and the Cargo build, is under ``~/.cache/neutrino/rustdesk``.

Needs rustup and ``cargo-ndk``, ``nasm``, ``unzip``, ``patch`` and a host
libclang for bindgen: the system's, or the directory ``LIBCLANG_PATH``
names. The NDK release and the Rust toolchain RustDesk's own CI pins are
fetched here; the two Android targets are added to that toolchain.

Not pure: downloads, unpacks and compiles.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402
from shared import cores_cache  # noqa: E402

# --- the pinned source ---
RUSTDESK_MOBILE_TAG = "1.4.9"
RUSTDESK_MOBILE_COMMIT = "6c578292e8ebbbec708b76986ba8c4bc7c509747"  # scan: allow
RUSTDESK_MOBILE_ARCHIVE_URL = (
    "https://github.com/rustdesk/rustdesk/archive/refs/tags/1.4.9.tar.gz"
)
RUSTDESK_MOBILE_ARCHIVE_SHA256 = (
    "1769fcc51751aab91bc0cfa691723722f51d3693ce3ddea3d92cfb1c319100e0"  # scan: allow
)
# The libs/hbb_common submodule at the commit the tag records.
RUSTDESK_MOBILE_HBB_COMMON_COMMIT = (
    "7e1c392c62d39c364127307cd408421dd5f8cfb0"  # scan: allow
)
RUSTDESK_MOBILE_HBB_COMMON_URL = (
    "https://github.com/rustdesk/hbb_common/archive/"
    f"{RUSTDESK_MOBILE_HBB_COMMON_COMMIT}.tar.gz"
)
RUSTDESK_MOBILE_HBB_COMMON_SHA256 = (
    "e108a197f00ae5b77a810a213d391469f8659ef51d7c975d858e5c1e0e22a899"  # scan: allow
)

# --- the toolchain RustDesk's CI pins (.github/workflows/flutter-build.yml) ---
RUSTDESK_MOBILE_NDK = "r28c"
RUSTDESK_MOBILE_NDK_URL = (
    "https://dl.google.com/android/repository/android-ndk-r28c-linux.zip"
)
RUSTDESK_MOBILE_NDK_SHA256 = (
    "dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f"  # scan: allow
)
RUSTDESK_MOBILE_RUST_TOOLCHAIN = "1.75"
RUSTDESK_MOBILE_VCPKG_COMMIT = "120deac3062162151622ca4860575a33844ba10b"  # scan: allow
RUSTDESK_MOBILE_VCPKG_URL = (
    f"https://github.com/microsoft/vcpkg/archive/{RUSTDESK_MOBILE_VCPKG_COMMIT}.tar.gz"
)
RUSTDESK_MOBILE_VCPKG_SHA256 = (
    "f3b1ec711fa1ba291efd75e27983898a37be15760dfe129a406448fa7377b31d"  # scan: allow
)
# The ports vcpkg.json names for Android, built for the target alone.
RUSTDESK_MOBILE_VCPKG_PORTS = (
    "aom",
    "cpu-features",
    "ffmpeg",
    "libjpeg-turbo",
    "libvpx",
    "libyuv",
    "oboe",
    "opus",
)

# --- the build ---
# Per machine as the app names it: the Rust target, the vcpkg triplet, the
# extra ports, and the crate features.
RUSTDESK_MOBILE_ABIS = {
    "arm64-v8a": ("aarch64-linux-android", "arm64-android", (), "native,mediacodec"),
    "x86_64": ("x86_64-linux-android", "x64-android", ("mfx-dispatch",), "native"),
}
RUSTDESK_MOBILE_ANDROID_API = "21"
RUSTDESK_MOBILE_CRATE_LIBRARY = "liblibrustdesk.so"
RUSTDESK_MOBILE_LIBRARY = "librustdesk.so"
RUSTDESK_MOBILE_CXX_LIBRARY = "libc++_shared.so"
RUSTDESK_MOBILE_PATCH = Path(__file__).resolve().parent / "build_core_rustdesk.patch"
RUSTDESK_MOBILE_RECIPE = cores_cache.recipe(
    Path(__file__).resolve(), RUSTDESK_MOBILE_PATCH
)
RUSTDESK_MOBILE_CACHE = Path.home() / ".cache" / "neutrino" / "rustdesk"
RUSTDESK_MOBILE_OUTPUT = (
    REPO_ROOT / "client" / "android" / "app" / "src" / "main" / "jniLibs"
)


def fetch(url: str, sha256: str, name: str) -> Path:
    """Download one pinned file into the cache, once, and check it.

    Args:
        url: Where it is published.
        sha256: Its pinned digest.
        name: The file name in the cache.

    Returns:
        The checked file.

    Raises:
        SystemExit: When the file is not the one pinned.
    """
    downloads = RUSTDESK_MOBILE_CACHE / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    target = downloads / name
    if not target.exists():
        print(f"downloading {url}")
        partial = target.with_suffix(".part")
        with urllib.request.urlopen(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.rename(target)
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != sha256:
        target.unlink()
        raise SystemExit(f"{name} sha256 {digest.hexdigest()} is not the pinned one")
    return target


def unpack(archive: Path, commit: str, target: Path) -> None:
    """Unpack a GitHub source archive into ``target``, checking its commit.

    Args:
        archive: The checked archive.
        commit: The commit its header must name.
        target: The directory its tree goes into, replaced.

    Raises:
        SystemExit: When the archive names another commit.
    """
    with tarfile.open(archive) as tar:
        named = tar.pax_headers.get("comment", "")
        if named != commit:
            raise SystemExit(f"{archive.name} names commit {named!r}")
        top = tar.getmembers()[0].name.split("/")[0]
        if target.exists():
            shutil.rmtree(target)
        staging = target.parent / f"{target.name}.unpack"
        if staging.exists():
            shutil.rmtree(staging)
        tar.extractall(staging, filter="fully_trusted")
        (staging / top).rename(target)
        staging.rmdir()


def fetch_source(patch_key: str) -> Path:
    """The patched tree for this source commit and patch, unpacked once.

    Args:
        patch_key: The patch's digest prefix.

    Returns:
        The root of the tree.
    """
    root = RUSTDESK_MOBILE_CACHE / f"source-{RUSTDESK_MOBILE_COMMIT[:12]}-{patch_key}"
    if (root / ".patched").exists():
        return root
    archive = fetch(
        RUSTDESK_MOBILE_ARCHIVE_URL,
        RUSTDESK_MOBILE_ARCHIVE_SHA256,
        f"rustdesk-{RUSTDESK_MOBILE_TAG}.tar.gz",
    )
    submodule = fetch(
        RUSTDESK_MOBILE_HBB_COMMON_URL,
        RUSTDESK_MOBILE_HBB_COMMON_SHA256,
        f"hbb_common-{RUSTDESK_MOBILE_HBB_COMMON_COMMIT[:7]}.tar.gz",
    )
    unpack(archive, RUSTDESK_MOBILE_COMMIT, root)
    unpack(submodule, RUSTDESK_MOBILE_HBB_COMMON_COMMIT, root / "libs" / "hbb_common")
    _run(["patch", "-p1", "--input", str(RUSTDESK_MOBILE_PATCH)], root)
    (root / ".patched").touch()
    return root


def fetch_ndk() -> Path:
    """The NDK release RustDesk builds with, unpacked once.

    Returns:
        The NDK's root.
    """
    root = RUSTDESK_MOBILE_CACHE / f"android-ndk-{RUSTDESK_MOBILE_NDK}"
    if (root / "source.properties").exists():
        return root
    archive = fetch(
        RUSTDESK_MOBILE_NDK_URL,
        RUSTDESK_MOBILE_NDK_SHA256,
        f"android-ndk-{RUSTDESK_MOBILE_NDK}-linux.zip",
    )
    if root.exists():
        shutil.rmtree(root)
    _run(["unzip", "-q", str(archive)], RUSTDESK_MOBILE_CACHE)
    return root


def build_vcpkg_ports(source: Path, ndk: Path) -> Path:
    """Build the codec libraries for every machine, once per source commit.

    Args:
        source: The RustDesk tree, whose ``res/vcpkg`` overlay ports are used.
        ndk: The NDK's root.

    Returns:
        The vcpkg root, whose ``installed/<triplet>`` the crate links from.
    """
    root = RUSTDESK_MOBILE_CACHE / f"vcpkg-{RUSTDESK_MOBILE_VCPKG_COMMIT[:12]}"
    if not (root / "vcpkg").exists():
        archive = fetch(
            RUSTDESK_MOBILE_VCPKG_URL,
            RUSTDESK_MOBILE_VCPKG_SHA256,
            f"vcpkg-{RUSTDESK_MOBILE_VCPKG_COMMIT[:7]}.tar.gz",
        )
        unpack(archive, RUSTDESK_MOBILE_VCPKG_COMMIT, root)
        _run(["./bootstrap-vcpkg.sh", "-disableMetrics"], root)
    environment = dict(os.environ, ANDROID_NDK_HOME=str(ndk), VCPKG_ROOT=str(root))
    for _, triplet, extra_ports, _ in RUSTDESK_MOBILE_ABIS.values():
        stamp = root / "installed" / f"{triplet}.{RUSTDESK_MOBILE_COMMIT[:12]}"
        if stamp.exists():
            continue
        command = ["./vcpkg", "install", "--classic", "--triplet", triplet]
        command += [f"--overlay-ports={source / 'res' / 'vcpkg'}"]
        command += [*RUSTDESK_MOBILE_VCPKG_PORTS, *extra_ports]
        _run(command, root, environment)
        stamp.touch()
    return root


def build_crate(source: Path, ndk: Path, vcpkg: Path, output: Path) -> None:
    """Compile the crate for every machine into ``output``.

    Args:
        source: The patched tree.
        ndk: The NDK's root.
        vcpkg: The vcpkg root holding the codec libraries.
        output: Where each machine's two libraries go, one directory per ABI.
    """
    toolchain = RUSTDESK_MOBILE_RUST_TOOLCHAIN
    targets = [target for target, _, _, _ in RUSTDESK_MOBILE_ABIS.values()]
    _run(["rustup", "toolchain", "install", toolchain, "--profile", "minimal"], source)
    _run(["rustup", "target", "add", "--toolchain", toolchain, *targets], source)
    target_dir = RUSTDESK_MOBILE_CACHE / "target"
    environment = dict(
        os.environ,
        ANDROID_NDK_HOME=str(ndk),
        ANDROID_NDK_ROOT=str(ndk),
        VCPKG_ROOT=str(vcpkg),
        CARGO_TARGET_DIR=str(target_dir),
    )
    sysroot = ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot"
    for abi, (target, _, _, features) in RUSTDESK_MOBILE_ABIS.items():
        command = ["cargo", f"+{toolchain}", "ndk"]
        command += ["--platform", RUSTDESK_MOBILE_ANDROID_API, "--target", target]
        command += ["build", "--locked", "--release", "--lib", "--features", features]
        _run(command, source, environment)
        destination = output / abi
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            target_dir / target / "release" / RUSTDESK_MOBILE_CRATE_LIBRARY,
            destination / RUSTDESK_MOBILE_LIBRARY,
        )
        shutil.copy2(
            sysroot / "usr" / "lib" / target / RUSTDESK_MOBILE_CXX_LIBRARY, destination
        )


def _check_tools() -> None:
    """Refuse to build without the tools the build runs.

    Raises:
        SystemExit: When one is missing.
    """
    for tool in ("rustup", "cargo", "cargo-ndk", "nasm", "unzip", "patch"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed to build RustDesk and is not on the path")


def _run(command: list, cwd: Path, environment: "dict | None" = None) -> None:
    """Run one build step, failing the build on an error."""
    print(" ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{command[0]} {command[1]} exited {result.returncode}")


def main() -> int:
    """Build the libraries, or take them from the cache, and copy them into the app.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument(
        "--output",
        default=str(RUSTDESK_MOBILE_OUTPUT),
        help="the jniLibs directory to fill",
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="build even when the cache has them"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cache names and stop"
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    if arguments.cache_key:
        for abi in RUSTDESK_MOBILE_ABIS:
            print(
                cores_cache.cache_key(
                    "rustdesk", RUSTDESK_MOBILE_COMMIT, abi, RUSTDESK_MOBILE_RECIPE
                )
            )
        return 0
    cached = {
        abi: cores_cache.cache_dir(
            "rustdesk", RUSTDESK_MOBILE_COMMIT, abi, RUSTDESK_MOBILE_RECIPE
        )
        for abi in RUSTDESK_MOBILE_ABIS
    }
    if arguments.rebuild or not all(map(cores_cache.is_cached, cached.values())):
        _check_tools()
        started = time.monotonic()
        patch_key = hashlib.sha256(RUSTDESK_MOBILE_PATCH.read_bytes()).hexdigest()[:12]
        source = fetch_source(patch_key)
        ndk = fetch_ndk()
        vcpkg = build_vcpkg_ports(source, ndk)
        built = RUSTDESK_MOBILE_CACHE / "built"
        if built.exists():
            shutil.rmtree(built)
        build_crate(source, ndk, vcpkg, built)
        for abi, directory in cached.items():
            cores_cache.store(built / abi, directory)
        print(
            f"rustdesk {RUSTDESK_MOBILE_TAG} ({RUSTDESK_MOBILE_COMMIT[:12]}) "
            f"built in {time.monotonic() - started:.0f}s"
        )
    else:
        print(f"rustdesk {RUSTDESK_MOBILE_TAG} from the cache")
    output = Path(arguments.output).resolve()
    for abi, directory in cached.items():
        cores_cache.install(directory, output / abi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
