#!/usr/bin/env bash
# Build the Windows installer on the Windows box and bring it home.
#
#   ./push_windows.sh            toolchain, tree, build, fetch to dist/
#   ./push_windows.sh --build    tree and build only, the toolchain is there
#
# The tree is what git tracks, nothing else: no .venv, no node_modules, no
# local dist/, so the box builds what a checkout would.

source "$(dirname "$0")/../common.sh"

[ -n "$(win_ip)" ] || { echo "no windows box in state/; run up.sh first" >&2; exit 1; }
ONLY_BUILD=0
[ "${1:-}" = "--build" ] && ONLY_BUILD=1

echo "== packing the tree"
pack_tree
du -h "$STATE/src.tgz" | cut -f1

echo "== pushing to $(win_ip)"
ssh_win 'New-Item -Force -ItemType Directory -Path C:\neutrino, C:\neutrino\src | Out-Null'
scp "${SSH_OPTS[@]}" "$STATE/src.tgz" "$HERE"/windows/*.ps1 "$WIN_USER@$(win_ip):C:/neutrino/"

if [ "$ONLY_BUILD" = 0 ]; then
    echo "== toolchain"
    ssh_win 'powershell -ExecutionPolicy Bypass -File C:\neutrino\toolchain.ps1'
fi

echo "== unpacking"
ssh_win 'Remove-Item -Recurse -Force C:\neutrino\src -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Path C:\neutrino\src | Out-Null; tar -xzf C:\neutrino\src.tgz -C C:\neutrino\src'

echo "== building"
ssh_win 'powershell -ExecutionPolicy Bypass -File C:\neutrino\build.ps1'

echo "== fetching to dist/"
mkdir -p "$REPO/dist"
scp "${SSH_OPTS[@]}" "$WIN_USER@$(win_ip):C:/neutrino/dist/*.msi" "$REPO/dist/"
ls -la "$REPO"/dist/*.msi
basename "$(ls "$REPO"/dist/*amd64.msi | head -1)" > "$STATE/msi_name"
echo "built: $(state msi_name)"
