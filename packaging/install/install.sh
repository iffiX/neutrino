#!/bin/sh
# Install one Neutrino package on macOS or Linux: the hub, the agent or the
# client.
#
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
#   curl -fsSL https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.sh | sh
#
# EDITION is the edition this script installs: intl from GitHub, cn from
# Gitee, where the latest release's tag is read from the API first.
# NEUTRINO_VERSION names the release, such as v0.5.0; the latest when unset.
# NEUTRINO_ASSET_DIR names a directory holding SHA256SUMS and the packages,
# which are installed from there with nothing downloaded.
#
# Run as a person, the script asks for the sudo password once, before it
# downloads anything, and keeps sudo's ticket fresh until it ends: the
# install, the hub's setup and the hub's own agent ask nothing more. An
# account sudo already lets in without a password is asked nothing.
set -eu

# The edition this script installs; the mainland source tree stamps it cn.
EDITION="intl"
RELEASES="https://github.com/iffiX/neutrino/releases"
CN_RELEASES="https://gitee.com/iffiX/neutrino/releases"
CN_LATEST_RELEASE_API="https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest"
OS_RELEASE=/etc/os-release
# The agent's binding to its hub on each system: a machine that holds one
# has joined, and is not told to join again.
AGENT_BINDING_LINUX=/etc/neutrino/agent/agent.json
AGENT_BINDING_MACOS="/Library/Application Support/Neutrino/agent/config/agent.json"
# The hub's command where its package puts it on each system, which a root
# shell's PATH may not name.
HUB_COMMAND_LINUX=/usr/bin/nhub
HUB_COMMAND_MACOS=/usr/local/bin/nhub
# The hub's panel settings on each system: a hub whose settings hold a
# password hash has been set up.
HUB_SETTINGS_LINUX=/etc/neutrino/hub/web/settings.json
HUB_SETTINGS_MACOS="/Library/Application Support/Neutrino/hub/config/web/settings.json"

fail() {
    echo "$1" >&2
    exit 1
}

# The machine as the package names spell it.
machine_name() {
    case "$1" in
        arm64 | aarch64) echo arm64 ;;
        x86_64 | amd64) echo amd64 ;;
        *) return 1 ;;
    esac
}

# The Linux package family a distribution installs: deb, rpm or arch.
linux_family() {
    [ -r "$1" ] || return 1
    ids=$(
        # shellcheck disable=SC1090
        . "$1"
        echo "${ID:-} ${ID_LIKE:-}"
    )
    for id in $ids; do
        case "$id" in
            debian | ubuntu | raspbian) echo deb && return 0 ;;
            fedora | rhel | centos | rocky | almalinux) echo rpm && return 0 ;;
            arch | archlinux | manjaro | endeavouros) echo arch && return 0 ;;
        esac
    done
    return 1
}

# The pattern SHA256SUMS names the package by, with any version.
asset_pattern() {
    component=$1
    kind=$2
    machine=$3
    case "$kind" in
        macos) echo "neutrino-$component-[0-9][^ ]*-macos-$machine\\.pkg" ;;
        deb) echo "neutrino-${component}_[0-9][^_ ]*_$machine\\.deb" ;;
        rpm)
            if [ "$machine" = amd64 ]; then
                rpm_machine=x86_64
            else
                rpm_machine=aarch64
            fi
            echo "neutrino-$component-[0-9][^ ]*-1\\.$rpm_machine\\.rpm"
            ;;
        arch)
            [ "$machine" = amd64 ] || return 1
            echo "neutrino-$component-[0-9][^ ]*-1-x86_64\\.pkg\\.tar\\.zst"
            ;;
    esac
}

# The line of SHA256SUMS naming the package, as "<sha256> <name>".
find_asset() {
    sed -n -E "s/^([0-9a-f]{64}) [ *]?($2)\$/\\1 \\2/p" "$1" | head -n 1
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        shasum -a 256 "$1" | cut -d ' ' -f 1
    fi
}

fetch() {
    curl -fsSL --retry 3 -o "$2" "$1" || fail "Downloading $1 failed."
}

# Ask for the sudo password once unless sudo already runs a command without
# one, and keep the ticket fresh in the background while the script runs by
# running a command, which an account without a password also may. Prints
# the keeper's pid; nothing when run as root.
hold_root() {
    [ -n "$1" ] || return 0
    command -v sudo >/dev/null 2>&1 \
        || fail "Run this as root, or install sudo first."
    if ! sudo -n true 2>/dev/null; then
        echo "Neutrino asks for administrator rights once, to install the package." >&2
        sudo -v || fail "sudo did not grant administrator rights; nothing was installed."
    fi
    (
        while sleep 30 && kill -0 "$2" 2>/dev/null; do
            sudo -n true 2>/dev/null || exit 0
        done
    ) </dev/null >/dev/null 2>&1 &
    echo "$!"
}

# Where the release's files are, for this script's edition. A cn release is
# found by its tag, which the API names for the latest one.
release_base() {
    if [ "$EDITION" != cn ]; then
        if [ -n "${NEUTRINO_VERSION:-}" ]; then
            echo "$RELEASES/download/$NEUTRINO_VERSION"
        else
            echo "$RELEASES/latest/download"
        fi
        return 0
    fi
    tag=${NEUTRINO_VERSION:-}
    if [ -z "$tag" ]; then
        fetch "$CN_LATEST_RELEASE_API" "$1/latest.json"
        tag=$(sed -n -E 's/.*"tag_name" *: *"([^"]+)".*/\1/p' "$1/latest.json" | head -n 1)
        [ -n "$tag" ] || fail "The latest release at $CN_LATEST_RELEASE_API names no tag."
    fi
    echo "$CN_RELEASES/download/$tag"
}

main() {
    component=${1:-hub}
    case "$component" in
        hub | agent | client) ;;
        *) fail "Name hub, agent or client to install, not $component." ;;
    esac

    system=$(uname -s)
    machine=$(machine_name "$(uname -m)") \
        || fail "No Neutrino package is published for $(uname -m)."
    case "$system" in
        Darwin) kind=macos ;;
        Linux)
            kind=$(linux_family "$OS_RELEASE") \
                || fail "No Neutrino package is published for this Linux distribution."
            ;;
        *) fail "No Neutrino package is published for $system." ;;
    esac
    pattern=$(asset_pattern "$component" "$kind" "$machine") \
        || fail "No Neutrino $component package is published for $kind on $machine."

    if [ "$(id -u)" = 0 ]; then
        as_root=""
    else
        as_root=sudo
    fi

    keeper=$(hold_root "$as_root" "$$") || exit 1
    work=$(mktemp -d)
    trap 'rm -rf "$work"; [ -z "$keeper" ] || kill "$keeper" 2>/dev/null || true' EXIT
    if [ -n "${NEUTRINO_ASSET_DIR:-}" ]; then
        source_dir=$NEUTRINO_ASSET_DIR
        [ -f "$source_dir/SHA256SUMS" ] || fail "There is no SHA256SUMS in $source_dir."
    else
        base=$(release_base "$work") || exit 1
        source_dir=$work
        fetch "$base/SHA256SUMS" "$work/SHA256SUMS"
    fi

    found=$(find_asset "$source_dir/SHA256SUMS" "$pattern")
    [ -n "$found" ] \
        || fail "The release publishes no Neutrino $component package for $kind on $machine."
    expected=${found%% *}
    name=${found#* }
    if [ -z "${NEUTRINO_ASSET_DIR:-}" ]; then
        fetch "$base/$name" "$work/$name"
    fi
    package="$source_dir/$name"
    [ -f "$package" ] || fail "There is no $name in $source_dir."
    [ "$(sha256_of "$package")" = "$expected" ] \
        || fail "$name does not match its SHA256SUMS line; nothing was installed."
    case "$package" in
        /*) ;;
        *) package="$(pwd)/$package" ;;
    esac

    echo "Installing $name"
    case "$kind" in
        macos) $as_root installer -pkg "$package" -target / ;;
        deb) $as_root apt-get install -y "$package" ;;
        rpm) $as_root dnf install -y "$package" ;;
        arch) $as_root pacman -U --noconfirm "$package" ;;
    esac

    case "$component" in
        agent)
            if [ "$kind" = macos ]; then
                binding=$AGENT_BINDING_MACOS
            else
                binding=$AGENT_BINDING_LINUX
            fi
            if $as_root ${as_root:+-n} grep -Eq '"token"[[:space:]]*:[[:space:]]*"[^"]' "$binding" 2>/dev/null; then
                return 0
            fi
            echo "Next, join this machine to a hub: ${as_root:+$as_root }nagent join '<enrollment link from the hub's Devices page>'"
            return 0
            ;;
        client)
            echo "Next, join this computer to a hub: nclient join '<client link from the hub's Clients page>'"
            return 0
            ;;
    esac
    if [ "$kind" = macos ]; then
        nhub=$HUB_COMMAND_MACOS
        settings=$HUB_SETTINGS_MACOS
    else
        nhub=$HUB_COMMAND_LINUX
        settings=$HUB_SETTINGS_LINUX
    fi
    if $as_root ${as_root:+-n} grep -Eq '"admin_password_hash"[[:space:]]*:[[:space:]]*"[$]' "$settings" 2>/dev/null; then
        address=$($as_root ${as_root:+-n} "$nhub" open --print 2>/dev/null) || address=""
        if [ -n "$address" ]; then
            echo "The hub was upgraded; its panel is at: $address"
        else
            echo "The hub was upgraded; ${as_root:+$as_root }nhub open opens its panel."
        fi
        return 0
    fi
    if (: </dev/tty) 2>/dev/null; then
        $as_root "$nhub" setup </dev/tty
        return
    fi
    address=$($as_root ${as_root:+-n} "$nhub" open --print 2>/dev/null) || address=""
    if [ -n "$address" ]; then
        echo "Next, set the hub up in a browser at: $address"
    else
        echo "Next, set the hub up: ${as_root:+$as_root }nhub open"
    fi
}

main "$@"
