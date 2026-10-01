"""Build the iOS app, once the Xcode project exists under client/ios.

    python3 packaging/build/build_client_ios.py --output-dir dist/

Runs on: macOS with Xcode. ``client/ios`` holds no Xcode project yet, so this
says what it will run and stops: ``xcodebuild archive`` of the app scheme
for a generic iOS device, then ``xcodebuild -exportArchive`` into an
unsigned ``neutrino-client-<version>-ios.ipa``.

Not pure: will run xcodebuild.
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IOS_DIR = REPO_ROOT / "client" / "ios"

# What the build will run, once there is a project to run it on.
XCODEBUILD_STEPS = (
    "xcodebuild archive -scheme Neutrino -destination 'generic/platform=iOS' "
    "-archivePath build/Neutrino.xcarchive CODE_SIGNING_ALLOWED=NO",
    "xcodebuild -exportArchive -archivePath build/Neutrino.xcarchive "
    "-exportPath <output-dir> -exportOptionsPlist ExportOptions.plist",
)


def main() -> int:
    """Say what the build will run.

    Returns:
        The process exit status: 1, since nothing is built yet.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .ipa")
    parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit(f"{Path(__file__).name} runs on macOS; this is {sys.platform}")
    if shutil.which("xcodebuild") is None:
        raise SystemExit("Xcode is needed and xcodebuild is not on the path")
    if not any(IOS_DIR.glob("*.xcodeproj")):
        print("client/ios has no Xcode project yet; once it has, this runs:")
        for step in XCODEBUILD_STEPS:
            print(f"  {step}")
        return 1
    raise SystemExit("client/ios has an Xcode project, and this script does not build it yet")


if __name__ == "__main__":
    sys.exit(main())
