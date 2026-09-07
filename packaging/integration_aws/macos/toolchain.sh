#!/usr/bin/env bash
# Runs on the Mac. What build_pkg.py needs beyond what Amazon's image already
# carries: the image has the command line tools, so pkgbuild, productbuild,
# codesign, install_name_tool and pkgutil are there, and Homebrew. What it
# lacks is a Python new enough to run the build scripts.

set -euo pipefail

echo "== command line tools"
xcode-select -p
for tool in pkgutil install_name_tool codesign pkgbuild productbuild; do
    command -v "$tool" > /dev/null || { echo "missing $tool" >&2; exit 1; }
done

echo "== python"
if ! command -v python3.13 > /dev/null; then
    brew install -q python@3.13
fi
python3.13 --version
echo "toolchain ready"
