#!/usr/bin/env bash
# Runs on the Mac. Builds the client's pkg from the tree pushed to
# ~/neutrino/src, into ~/neutrino/dist.

set -euo pipefail

SRC="$HOME/neutrino/src"
DIST="$HOME/neutrino/dist"
mkdir -p "$DIST"
rm -f "$DIST"/*.pkg

cd "$SRC"
python3.13 client/packaging/build_pkg.py --output-dir "$DIST" --architecture arm64
ls -la "$DIST"
