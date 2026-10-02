#!/bin/sh
# Install one Neutrino package on macOS or Linux: the hub, the agent or the
# client.
#
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
#
# NEUTRINO_VERSION names the release, such as v0.5.0; the latest when unset.
# NEUTRINO_ASSET_DIR names a directory holding SHA256SUMS and the packages,
# which are installed from there with nothing downloaded.
set -eu

RELEASES="https://github.com/iffiX/neutrino/releases"
OS_RELEASE=/etc/os-release

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

    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    if [ -n "${NEUTRINO_ASSET_DIR:-}" ]; then
        source_dir=$NEUTRINO_ASSET_DIR
        [ -f "$source_dir/SHA256SUMS" ] || fail "There is no SHA256SUMS in $source_dir."
    else
        if [ -n "${NEUTRINO_VERSION:-}" ]; then
            base="$RELEASES/download/$NEUTRINO_VERSION"
        else
            base="$RELEASES/latest/download"
        fi
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

    [ "$component" = hub ] || return 0
    if (: </dev/tty) 2>/dev/null; then
        $as_root nhub setup </dev/tty
    else
        echo "Set the hub up with: sudo nhub setup"
    fi
}

main "$@"
