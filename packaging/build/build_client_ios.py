"""Build the iOS app's unsigned .ipa.

    python3 packaging/build/build_client_ios.py --output-dir dist/

Runs on: macOS with Xcode and XcodeGen. ``xcodegen generate`` writes the
project from ``client/ios/project.yml``, ``xcodebuild`` builds the app for
``generic/platform=iOS`` with code signing off, and the ``.app`` is zipped
under ``Payload/`` as ``neutrino-client-<version>-ios.ipa``. Before the zip,
the app's icon is drawn from ``images/icons/neutrino.png`` into an asset
catalog under ``client/ios/build/icon`` and compiled into the ``.app`` by
``actool``, its keys merged into the app's ``Info.plist``. The version, read
off the hub's pyproject, and the edition reach the app as the build settings
``MARKETING_VERSION``, ``CURRENT_PROJECT_VERSION`` and ``NEUTRINO_EDITION``.
``--build-settings`` prints those settings, one ``NAME=value`` per line, for
the CI job's ``xcodebuild test``, and builds nothing.

Not pure: runs xcodegen, xcodebuild, sips and actool, writes the .ipa.
"""

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402

IOS_DIR = REPO_ROOT / "client" / "ios"

# The scheme and the app's product name, as project.yml names them.
IOS_SCHEME = "Neutrino"
IOS_APP = "Neutrino.app"

# Where the build writes: xcodebuild's derived data, and the icon's asset
# catalog with the Info.plist keys actool writes for it.
IOS_BUILD_DIR = IOS_DIR / "build"
IOS_ICON_CATALOG = IOS_BUILD_DIR / "icon" / "Assets.xcassets"
IOS_ICON_PLIST = IOS_BUILD_DIR / "icon" / "partial.plist"
IOS_ICON_SOURCE = REPO_ROOT / "images" / "icons" / "neutrino.png"

# The one icon size iOS takes from Xcode 14 on, and the catalog naming it.
IOS_ICON_EDGE = 1024
IOS_ICON_CONTENTS = (
    '{"images":[{"filename":"icon.png","idiom":"universal","platform":"ios",'
    '"size":"1024x1024"}],"info":{"author":"xcode","version":1}}'
)


def main() -> int:
    """Build the .ipa, or print the build settings.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument("--output-dir", default="dist", help="where to write the .ipa")
    parser.add_argument(
        "--build-settings",
        action="store_true",
        help="print the version and edition settings and stop",
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    settings = build_settings(_version(), arguments.edition)
    if arguments.build_settings:
        print("\n".join(settings))
        return 0
    _check_tools()

    shutil.rmtree(IOS_BUILD_DIR, ignore_errors=True)
    subprocess.run(["xcodegen", "generate"], cwd=IOS_DIR, check=True)
    derived = IOS_BUILD_DIR / "derived"
    command = [
        "xcodebuild",
        "-project",
        "Neutrino.xcodeproj",
        "-scheme",
        IOS_SCHEME,
        "-configuration",
        "Release",
        "-sdk",
        "iphoneos",
        "-destination",
        "generic/platform=iOS",
        "-derivedDataPath",
        str(derived),
        "-skipPackagePluginValidation",
        "CODE_SIGNING_ALLOWED=NO",
        *settings,
        "build",
    ]
    result = subprocess.run(command, cwd=IOS_DIR, check=False)
    if result.returncode != 0:
        raise SystemExit(f"xcodebuild exited {result.returncode}")

    app = derived / "Build" / "Products" / "Release-iphoneos" / IOS_APP
    if not app.is_dir():
        raise SystemExit(f"xcodebuild wrote no {IOS_APP} under {app.parent}")
    _add_icon(app)
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ipa = output_dir / f"neutrino-client-{_version()}-ios.ipa"
    _zip_payload(app, ipa)
    print(f"wrote {ipa} ({ipa.stat().st_size // 1024 // 1024} MiB)")
    return 0


def build_settings(version: str, edition: str) -> list:
    """The xcodebuild settings that stamp the version and the edition.

    Args:
        version: The release's version.
        edition: ``intl`` or ``cn``.

    Returns:
        ``NAME=value`` strings.
    """
    return [
        f"MARKETING_VERSION={version}",
        f"CURRENT_PROJECT_VERSION={version}",
        f"NEUTRINO_EDITION={edition}",
    ]


def _add_icon(app: Path) -> None:
    """Put the app's icon into the built app.

    sips draws it into an asset catalog, actool compiles the catalog into the
    app, and the keys actool names the icon under join the app's Info.plist.

    Args:
        app: The built ``.app`` directory.

    Raises:
        subprocess.CalledProcessError: When sips or actool fails.
    """
    icon_set = IOS_ICON_CATALOG / "AppIcon.appiconset"
    icon_set.mkdir(parents=True)
    (IOS_ICON_CATALOG / "Contents.json").write_text(
        '{"info":{"author":"xcode","version":1}}'
    )
    (icon_set / "Contents.json").write_text(IOS_ICON_CONTENTS)
    subprocess.run(
        [
            "sips",
            "-z",
            str(IOS_ICON_EDGE),
            str(IOS_ICON_EDGE),
            str(IOS_ICON_SOURCE),
            "--out",
            str(icon_set / "icon.png"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "xcrun",
            "actool",
            str(IOS_ICON_CATALOG),
            "--compile",
            str(app),
            "--platform",
            "iphoneos",
            "--minimum-deployment-target",
            "16.0",
            "--app-icon",
            "AppIcon",
            "--target-device",
            "iphone",
            "--target-device",
            "ipad",
            "--output-partial-info-plist",
            str(IOS_ICON_PLIST),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    info_path = app / "Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    with IOS_ICON_PLIST.open("rb") as stream:
        info.update(plistlib.load(stream))
    with info_path.open("wb") as stream:
        plistlib.dump(info, stream, fmt=plistlib.FMT_BINARY)


def _zip_payload(app: Path, ipa: Path) -> None:
    """Zip an app under ``Payload/``, keeping its symbolic links and modes.

    Args:
        app: The ``.app`` directory.
        ipa: The archive to write.
    """
    ipa.unlink(missing_ok=True)
    with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob("*")):
            name = Path("Payload") / app.name / path.relative_to(app)
            info = zipfile.ZipInfo(str(name))
            info.external_attr = (path.lstat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if path.is_symlink():
                archive.writestr(info, os.readlink(path))
            elif path.is_file():
                archive.writestr(info, path.read_bytes())


def _version() -> str:
    """The version the packages declare, read off the hub's pyproject.

    Raises:
        SystemExit: When the pyproject declares none.
    """
    text = (REPO_ROOT / "hub" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("hub/pyproject.toml declares no version")
    return match.group(1)


def _check_tools() -> None:
    """Refuse to start off macOS or without Xcode, XcodeGen and sips.

    Raises:
        SystemExit: When either is missing.
    """
    if sys.platform != "darwin":
        raise SystemExit(f"{Path(__file__).name} runs on macOS; this is {sys.platform}")
    for tool in ("xcodebuild", "xcodegen", "sips", "xcrun"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed and is not on the path")


if __name__ == "__main__":
    sys.exit(main())
