"""Build the Android app's apk, with the cores it carries.

    python3 packaging/build/build_client_android.py --variant debug --output-dir dist/

Runs on: Linux or macOS with JDK 17 and the Android SDK, ``ANDROID_HOME``
naming it. The NetBird, EasyTier and RustDesk cores come from the cores
cache, or are built when it does not have them, which needs what
``build_core_netbird.py``, ``build_core_easytier.py`` and
``build_core_rustdesk.py`` name.

Then ``gradlew assembleDebug`` or ``assembleRelease`` runs in
``client/android``. A release build is signed when the four variables
``ANDROID_KEYSTORE_B64``, ``ANDROID_KEYSTORE_PASSWORD``,
``ANDROID_KEY_ALIAS`` and ``ANDROID_KEY_PASSWORD`` are set, and unsigned
otherwise. The arm64-v8a apk is written as
``neutrino-client-<version>-android.apk``, the one published, and the x86_64
apk beside it as ``neutrino-client-<version>-android-x86_64.apk``, the one an
emulator runs. ``--cache-key`` prints the one name the cores are cached
under in CI and builds nothing.

Not pure: runs the core builds and Gradle, writes the apks.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = Path(__file__).resolve().parent
ANDROID_DIR = REPO_ROOT / "client" / "android"

# The scripts that put each core into the app, in the order they run.
CORE_SCRIPTS = (
    "build_core_netbird.py",
    "build_core_easytier.py",
    "build_core_rustdesk.py",
)

# The four variables the Gradle build signs a release with.
SIGNING_VARIABLES = (
    "ANDROID_KEYSTORE_B64",
    "ANDROID_KEYSTORE_PASSWORD",
    "ANDROID_KEY_ALIAS",
    "ANDROID_KEY_PASSWORD",
)

# The machine whose apk is published, and the one an emulator runs.
PUBLISHED_ABI = "arm64-v8a"
EMULATOR_ABI = "x86_64"


def main() -> int:
    """Build the apks.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--variant", choices=("debug", "release"), default="debug", help="what to build"
    )
    parser.add_argument("--output-dir", default="dist", help="where to write the apks")
    parser.add_argument(
        "--cache-key", action="store_true", help="print the cores' cache name and stop"
    )
    arguments = parser.parse_args()
    if arguments.cache_key:
        keys = [_run_core(script, "--cache-key") for script in CORE_SCRIPTS]
        print("cores-" + "-".join(" ".join(keys).split()))
        return 0
    _check_tools()

    for script in CORE_SCRIPTS:
        _run_core(script)
    signing = [name for name in SIGNING_VARIABLES if os.environ.get(name)]
    if arguments.variant == "release" and len(signing) != len(SIGNING_VARIABLES):
        print("the four signing variables are not all set; the release is unsigned")
    task = f"assemble{arguments.variant.capitalize()}"
    result = subprocess.run(
        [str(ANDROID_DIR / "gradlew"), "--no-daemon", task],
        cwd=ANDROID_DIR,
        check=False,
    )
    shutil.rmtree(ANDROID_DIR / "app" / "build" / "signing", ignore_errors=True)
    if result.returncode != 0:
        raise SystemExit(f"gradlew {task} exited {result.returncode}")

    version = _version()
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for abi, name in (
        (PUBLISHED_ABI, f"neutrino-client-{version}-android.apk"),
        (EMULATOR_ABI, f"neutrino-client-{version}-android-{EMULATOR_ABI}.apk"),
    ):
        built = _built_apk(arguments.variant, abi)
        shutil.copyfile(built, output_dir / name)
        print(f"wrote {output_dir / name} ({built.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _run_core(script: str, *arguments: str) -> str:
    """Run one core script, which puts its core into the app.

    Args:
        script: The script's name in this directory.
        *arguments: What it is run with.

    Returns:
        What it printed, when it was asked a question.

    Raises:
        SystemExit: When it fails.
    """
    command = [sys.executable, str(BUILD_DIR / script), *arguments]
    result = subprocess.run(
        command, capture_output=bool(arguments), text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"{script} exited {result.returncode}")
    return (result.stdout or "").strip()


def _built_apk(variant: str, abi: str) -> Path:
    """The apk Gradle wrote for one machine.

    Args:
        variant: ``debug`` or ``release``.
        abi: The machine.

    Returns:
        Its path; a release built with no key carries ``-unsigned``.

    Raises:
        SystemExit: When Gradle wrote neither.
    """
    directory = ANDROID_DIR / "app" / "build" / "outputs" / "apk" / variant
    for name in (f"app-{abi}-{variant}.apk", f"app-{abi}-{variant}-unsigned.apk"):
        if (directory / name).is_file():
            return directory / name
    raise SystemExit(f"gradle wrote no {variant} apk for {abi} under {directory}")


def _version() -> str:
    """The version the app declares in its gradle.properties.

    Raises:
        SystemExit: When it declares none.
    """
    for line in (ANDROID_DIR / "gradle.properties").read_text("utf-8").splitlines():
        if line.startswith("neutrinoVersion="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("client/android/gradle.properties declares no neutrinoVersion")


def _check_tools() -> None:
    """Refuse to start without Java and the Android SDK.

    Raises:
        SystemExit: When either is missing.
    """
    if shutil.which("java") is None:
        raise SystemExit("JDK 17 is needed and java is not on the path")
    if not os.environ.get("ANDROID_HOME"):
        raise SystemExit("the Android SDK is needed and ANDROID_HOME is not set")


if __name__ == "__main__":
    sys.exit(main())
