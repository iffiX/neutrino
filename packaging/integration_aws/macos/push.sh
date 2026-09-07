#!/usr/bin/env bash
# Build the macOS installer on the Mac and bring it home.
#
#   macos/push.sh            toolchain, tree, build, fetch to dist/
#   macos/push.sh --build    tree and build only, the toolchain is there

source "$(dirname "$0")/../common.sh"

[ -n "$(mac_ip)" ] || { echo "no mac in state/; run macos/up.sh first" >&2; exit 1; }
ONLY_BUILD=0
[ "${1:-}" = "--build" ] && ONLY_BUILD=1

echo "== packing the tree"
pack_tree
du -h "$STATE/src.tgz" | cut -f1

echo "== pushing to $(mac_ip)"
ssh_mac 'mkdir -p ~/neutrino/src'
scp "${SSH_OPTS[@]}" "$STATE/src.tgz" "$HERE"/macos/*.sh "$MAC_USER@$(mac_ip):neutrino/"

if [ "$ONLY_BUILD" = 0 ]; then
    echo "== toolchain"
    ssh_mac 'bash ~/neutrino/toolchain.sh'
fi

echo "== unpacking"
ssh_mac 'rm -rf ~/neutrino/src && mkdir -p ~/neutrino/src && tar -xzf ~/neutrino/src.tgz -C ~/neutrino/src'

echo "== building"
ssh_mac 'bash ~/neutrino/build.sh'

echo "== fetching to dist/"
mkdir -p "$REPO/dist"
scp "${SSH_OPTS[@]}" "$MAC_USER@$(mac_ip):neutrino/dist/*.pkg" "$REPO/dist/"
ls -la "$REPO"/dist/*.pkg
basename "$(ls "$REPO"/dist/*.pkg | head -1)" > "$STATE/pkg_name"
echo "built: $(state pkg_name)"
