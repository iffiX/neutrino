"""The transport's library for the iOS app, ``Mobile.xcframework``.

    python3 packaging/build/build_core_transport.py

Runs on: macOS with Xcode and the pinned Go; ``gomobile`` and ``gobind`` are
installed at the version ``transport/go.mod`` pins when they are missing.
``gomobile bind -target ios,iossimulator -iosversion 16.0`` over
``transport/mobile`` writes the framework with its device and Simulator
slices, cached under
``~/.cache/neutrino/cores/transport-<sources>-ios-arm64+simulator-<recipe>/`` as every
core is, ``<sources>`` being a digest of the transport's Go files, and
copied to ``client/ios/cores/transport/Mobile.xcframework``. ``--cache-key``
prints that cache name and builds nothing.

On Android the transport is bound into NetBird's ``.aar`` by
``build_core_netbird.py``, since an app loads one gomobile library.

Not pure: compiles and writes into the app's tree.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import cores_cache  # noqa: E402
from shared import go_build  # noqa: E402

TRANSPORT_MOBILE_PACKAGE = "./mobile"
TRANSPORT_MOBILE_TARGET = "ios,iossimulator"
TRANSPORT_MOBILE_IOS_VERSION = "16.0"
TRANSPORT_MOBILE_LIBRARY = "Mobile.xcframework"
TRANSPORT_MOBILE_ABI = "ios-arm64+simulator"
TRANSPORT_MOBILE_OUTPUT = REPO_ROOT / "client" / "ios" / "cores" / "transport"
TRANSPORT_MOBILE_RECIPE = cores_cache.recipe(Path(__file__).resolve())


def bind(output: Path) -> None:
    """Run ``gomobile bind`` for iOS into the framework.

    Args:
        output: The ``.xcframework`` to write.

    Raises:
        SystemExit: When the bind fails.
    """
    tools = go_build.install_gomobile()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(tools / "gomobile"),
        "bind",
        "-target",
        TRANSPORT_MOBILE_TARGET,
        "-iosversion",
        TRANSPORT_MOBILE_IOS_VERSION,
        "-trimpath",
        "-ldflags",
        "-s -w",
        "-o",
        str(output),
        TRANSPORT_MOBILE_PACKAGE,
    ]
    print(" ".join(command))
    environment = dict(
        os.environ,
        PATH=f"{tools}{os.pathsep}{os.environ.get('PATH', '')}",
        GOTOOLCHAIN="local",
    )
    result = subprocess.run(
        command, cwd=REPO_ROOT / "transport", env=environment, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"gomobile bind exited {result.returncode}")


def main() -> int:
    """Build the framework, or take it from the cache, and copy it into the app.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default=str(TRANSPORT_MOBILE_OUTPUT),
        help="the directory the framework is copied to",
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="build even when the cache has it"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cache name and stop"
    )
    arguments = parser.parse_args()
    sources = go_build.transport_source_digest()
    if arguments.cache_key:
        print(
            cores_cache.cache_key(
                "transport", sources, TRANSPORT_MOBILE_ABI, TRANSPORT_MOBILE_RECIPE
            )
        )
        return 0
    cached = cores_cache.cache_dir(
        "transport", sources, TRANSPORT_MOBILE_ABI, TRANSPORT_MOBILE_RECIPE
    )
    if arguments.rebuild or not cores_cache.is_cached(cached):
        if platform.system() != "Darwin":
            raise SystemExit("the iOS framework is built on macOS with Xcode")
        if shutil.which("xcodebuild") is None:
            raise SystemExit(
                "xcodebuild is needed to build the iOS framework and is not on the path"
            )
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="build_core_transport_") as scratch:
            built = Path(scratch) / "built"
            bind(built / TRANSPORT_MOBILE_LIBRARY)
            cores_cache.store(built, cached)
        print(
            f"transport {sources} built in {time.monotonic() - started:.0f}s: {cached}"
        )
    else:
        print(f"transport {sources} from the cache: {cached}")
    install_framework(cached, Path(arguments.output).resolve())
    return 0


def install_framework(cached: Path, destination: Path) -> None:
    """Copy the framework, a directory tree, from the cache into the app.

    Args:
        cached: The cache directory holding the framework.
        destination: The directory in the app the framework goes to.

    Raises:
        FileNotFoundError: When the cache holds no framework.
    """
    source = cached / TRANSPORT_MOBILE_LIBRARY
    if not source.is_dir():
        raise FileNotFoundError(f"{source} holds no framework")
    target = destination / TRANSPORT_MOBILE_LIBRARY
    if target.exists():
        shutil.rmtree(target)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    print(f"  {TRANSPORT_MOBILE_LIBRARY} -> {destination}")


if __name__ == "__main__":
    sys.exit(main())
