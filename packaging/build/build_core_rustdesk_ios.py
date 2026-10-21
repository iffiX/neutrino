"""RustDesk's iOS static library, built from its pinned source for the iPhone app.

    python3 packaging/build/build_core_rustdesk_ios.py

Runs on: macOS with Xcode. With the library already in the cores cache it
needs nothing else; building it needs rustup, ``patch`` and ``nasm``.

The app links the RustDesk crate for one machine, a device
(``aarch64-apple-ios``); a Simulator build links no core. The source, the
patch, the Rust toolchain and vcpkg are ``build_core_rustdesk.py``'s pins,
fetched by its helpers. The codec libraries are built with vcpkg for an
overlay ``arm64-ios`` triplet whose deployment target is the app's, and the
crate with ``cargo rustc --crate-type staticlib --features native``, whose
printed native-static-libs go into ``RustDesk.xcconfig`` beside
``liblibrustdesk.a``: a device build links the archive and compiles with
``NEUTRINO_RUSTDESK``. The two files are cached under
``~/.cache/neutrino/cores/rustdesk-<commit>-ios-arm64-<recipe>/``, the recipe
being the digest of both scripts and the patch, and copied to
``client/ios/cores/rustdesk/``, which ``client/ios/Neutrino.xcconfig``
includes. ``--cache-key`` prints the cache name and builds nothing.

What building fetches and keeps between runs is under
``~/.cache/neutrino/rustdesk``, beside what the Android build keeps.

Not pure: downloads, unpacks and compiles.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cores_cache  # noqa: E402

# The Android build beside this file: its pins and its fetch helpers.
import build_core_rustdesk as rustdesk  # noqa: E402

# --- the build ---
RUSTDESK_IOS_TARGET = "aarch64-apple-ios"
RUSTDESK_IOS_ABI = "ios-arm64"
RUSTDESK_IOS_FEATURES = "native"
RUSTDESK_IOS_DEPLOYMENT_TARGET = "16.0"
# The ports vcpkg.json names for iOS, but FFmpeg, which only hwcodec uses.
RUSTDESK_IOS_VCPKG_PORTS = ("aom", "libjpeg-turbo", "libvpx", "libyuv", "opus")
# The name scrap's build script reads the libraries from, overlaid to set the
# deployment target and build release libraries alone.
RUSTDESK_IOS_TRIPLET = "arm64-ios"
RUSTDESK_IOS_TRIPLET_TEXT = f"""\
set(VCPKG_TARGET_ARCHITECTURE arm64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_CMAKE_SYSTEM_NAME iOS)
set(VCPKG_OSX_DEPLOYMENT_TARGET {RUSTDESK_IOS_DEPLOYMENT_TARGET})
set(VCPKG_BUILD_TYPE release)
"""
RUSTDESK_IOS_LIBRARY = "liblibrustdesk.a"
RUSTDESK_IOS_XCCONFIG = "RustDesk.xcconfig"
RUSTDESK_IOS_RECIPE = cores_cache.recipe(
    Path(rustdesk.__file__).resolve(),
    Path(__file__).resolve(),
    rustdesk.RUSTDESK_MOBILE_PATCH,
)
RUSTDESK_IOS_OUTPUT = REPO_ROOT / "client" / "ios" / "cores" / "rustdesk"


def build_vcpkg_ports(source: Path) -> Path:
    """Build the codec libraries for a device, once per source commit.

    Args:
        source: The RustDesk tree, whose ``res/vcpkg`` overlay ports are used.

    Returns:
        The vcpkg root, whose ``installed/arm64-ios`` the crate links from.
    """
    root = rustdesk.fetch_vcpkg()
    commit = rustdesk.RUSTDESK_MOBILE_COMMIT[:12]
    stamp = root / "installed" / f"{RUSTDESK_IOS_TRIPLET}.{commit}"
    if stamp.exists():
        return root
    triplets = rustdesk.RUSTDESK_MOBILE_CACHE / "triplets-ios"
    triplets.mkdir(parents=True, exist_ok=True)
    (triplets / f"{RUSTDESK_IOS_TRIPLET}.cmake").write_text(RUSTDESK_IOS_TRIPLET_TEXT)
    command = ["./vcpkg", "install", "--classic", "--triplet", RUSTDESK_IOS_TRIPLET]
    command += [f"--overlay-ports={source / 'res' / 'vcpkg'}"]
    command += [f"--overlay-triplets={triplets}", *RUSTDESK_IOS_VCPKG_PORTS]
    _run(command, root, dict(os.environ, VCPKG_ROOT=str(root)))
    stamp.touch()
    return root


def build_crate(source: Path, vcpkg: Path, output: Path) -> None:
    """Compile the crate into ``output`` with the xcconfig that links it.

    Args:
        source: The patched tree.
        vcpkg: The vcpkg root holding the codec libraries.
        output: Where the archive and ``RustDesk.xcconfig`` go.

    Raises:
        SystemExit: When cargo fails or prints no native-static-libs.
    """
    toolchain = rustdesk.RUSTDESK_MOBILE_RUST_TOOLCHAIN
    _run(["rustup", "toolchain", "install", toolchain, "--profile", "minimal"], source)
    _run(
        ["rustup", "target", "add", "--toolchain", toolchain, RUSTDESK_IOS_TARGET],
        source,
    )
    target_dir = rustdesk.RUSTDESK_MOBILE_CACHE / "target"
    environment = dict(
        os.environ,
        VCPKG_ROOT=str(vcpkg),
        CARGO_TARGET_DIR=str(target_dir),
        IPHONEOS_DEPLOYMENT_TARGET=RUSTDESK_IOS_DEPLOYMENT_TARGET,
    )
    command = ["cargo", f"+{toolchain}", "rustc", "--locked", "--release", "--lib"]
    command += ["--target", RUSTDESK_IOS_TARGET, "--features", RUSTDESK_IOS_FEATURES]
    command += ["--crate-type", "staticlib", "--", "--print", "native-static-libs"]
    printed = _run_reading(command, source, environment)
    found = re.search(r"native-static-libs: (.*)", printed)
    if found is None:
        raise SystemExit("cargo printed no native-static-libs")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        target_dir / RUSTDESK_IOS_TARGET / "release" / RUSTDESK_IOS_LIBRARY,
        output / RUSTDESK_IOS_LIBRARY,
    )
    (output / RUSTDESK_IOS_XCCONFIG).write_text(xcconfig(found.group(1).split()))


def xcconfig(libraries: list) -> str:
    """The build settings that link the archive into a device build.

    Args:
        libraries: The linker arguments the archive's native-static-libs name.

    Returns:
        The text of ``RustDesk.xcconfig``.
    """
    archive = f'"$(SRCROOT)/cores/rustdesk/{RUSTDESK_IOS_LIBRARY}"'
    return (
        f"// Written by {Path(__file__).name}: a device build links the RustDesk core.\n"
        f"OTHER_LDFLAGS[sdk=iphoneos*] = $(inherited) {archive} {' '.join(libraries)}\n"
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS[sdk=iphoneos*] = "
        "$(inherited) NEUTRINO_RUSTDESK\n"
    )


def _check_tools() -> None:
    """Refuse to build off macOS or without the tools the build runs.

    Raises:
        SystemExit: When one is missing.
    """
    if sys.platform != "darwin":
        raise SystemExit(f"{Path(__file__).name} runs on macOS; this is {sys.platform}")
    for tool in ("rustup", "cargo", "nasm", "patch", "xcrun"):
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is needed to build RustDesk and is not on the path"
            )


def _run(command: list, cwd: Path, environment: "dict | None" = None) -> None:
    """Run one build step, failing the build on an error."""
    _run_reading(command, cwd, environment)


def _run_reading(command: list, cwd: Path, environment: "dict | None") -> str:
    """Run one build step, echoing and returning its output, failing on an error."""
    print(" ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    lines = []
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    if process.wait() != 0:
        raise SystemExit(f"{command[0]} {command[1]} exited {process.returncode}")
    return "".join(lines)


def main() -> int:
    """Build the library, or take it from the cache, and copy it into the app.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default=str(RUSTDESK_IOS_OUTPUT),
        help="the directory the app's build links from",
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="build even when the cache has it"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cache name and stop"
    )
    arguments = parser.parse_args()
    commit = rustdesk.RUSTDESK_MOBILE_COMMIT
    if arguments.cache_key:
        print(
            cores_cache.cache_key(
                "rustdesk", commit, RUSTDESK_IOS_ABI, RUSTDESK_IOS_RECIPE
            )
        )
        return 0
    cached = cores_cache.cache_dir(
        "rustdesk", commit, RUSTDESK_IOS_ABI, RUSTDESK_IOS_RECIPE
    )
    if arguments.rebuild or not cores_cache.is_cached(cached):
        _check_tools()
        started = time.monotonic()
        patch = rustdesk.RUSTDESK_MOBILE_PATCH.read_bytes()
        source = rustdesk.fetch_source(hashlib.sha256(patch).hexdigest()[:12])
        vcpkg = build_vcpkg_ports(source)
        built = rustdesk.RUSTDESK_MOBILE_CACHE / "built-ios"
        if built.exists():
            shutil.rmtree(built)
        build_crate(source, vcpkg, built)
        cores_cache.store(built, cached)
        print(
            f"rustdesk {rustdesk.RUSTDESK_MOBILE_TAG} ({commit[:12]}) for iOS "
            f"built in {time.monotonic() - started:.0f}s"
        )
    else:
        print(f"rustdesk {rustdesk.RUSTDESK_MOBILE_TAG} for iOS from the cache")
    cores_cache.install(cached, Path(arguments.output).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
