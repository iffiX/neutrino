#!/usr/bin/env bash
# Runs on the Mac. Builds the universal2 pkg from the tree pushed to
# ~/neutrino/src, into ~/neutrino/dist.

set -euo pipefail

SRC="$HOME/neutrino/src"
DIST="$HOME/neutrino/dist"
mkdir -p "$DIST"
rm -f "$DIST"/*.pkg

cd "$SRC"
python3.13 agent/packaging/build_pkg.py --output-dir "$DIST"
ls -la "$DIST"
