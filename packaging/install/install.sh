#!/bin/sh
# Install one Neutrino package on macOS or Linux: the hub, the agent or the
# client.
#
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh -s -- agent
#   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh
#
# EDITION is the edition whose package this script installs, and
# RELEASE_SITES the release sites its build stamped; a checkout names none.
# The latest release's tag is read from latest.json on the sites, and each
# file comes from the fastest site, the script moving to the next one on a
# stall. NEUTRINO_VERSION names the release, such as v0.5.0; the latest when
# unset. NEUTRINO_ASSET_DIR names a directory holding SHA256SUMS and the
# packages, which are installed from there with nothing downloaded.
#
# Run as a person, the script asks for the sudo password once, before it
# downloads anything, and keeps sudo's ticket fresh until it ends: the
# install, the hub's setup and the hub's own agent ask nothing more. An
# account sudo already lets in without a password is asked nothing. On the
# RHEL family EPEL is enabled under the same sudo before the install.
set -eu

# The edition this script installs; the mainland source tree stamps it cn.
EDITION="intl"
# The release sites, each as the address of a tag's files, {tag} in it, then
# the address of latest.json, every address parted by a space.
RELEASE_SITES=""
# How long a probe or a read of latest.json waits for a site, how long a
# download may receive nothing before its site counts as stalled, in seconds,
# and how many bytes a probe asks for.
PROBE_WAIT_S=5
STALL_S=20
PROBE_BYTES=1048576
OS_RELEASE=/etc/os-release
# The EPEL release package for RHEL, the major release and .noarch.rpm after
# it, as EPEL's own instructions name it.
EPEL_RELEASE_PREFIX=https://dl.fedoraproject.org/pub/epel/epel-release-latest-
# The agent's binding to its hub on each system: a machine that holds one
# has joined, and is not told to join again.
AGENT_BINDING_LINUX=/etc/neutrino/agent/agent.json
AGENT_BINDING_MACOS="/Library/Application Support/Neutrino/agent/config/agent.json"
# A person's client bindings under their home on each system: a person who
# holds one has joined, and is not told to join again.
CLIENT_BINDINGS_LINUX=.config/neutrino/client/client.json
CLIENT_BINDINGS_MACOS="Library/Application Support/Neutrino/client/client.json"
# The hub's command where its package puts it on each system, which a root
# shell's PATH may not name.
HUB_COMMAND_LINUX=/usr/bin/nhub
HUB_COMMAND_MACOS=/usr/local/bin/nhub
# The hub's panel settings on each system: a hub whose settings hold a
# password hash, not the example's placeholder, has been set up.
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

# Enable EPEL on the RHEL family, which every package's dependencies need
# there: the hub's fail2ban and arp-scan, the agent's and the client's
# xdotool. The steps are EPEL's own, CRB first: Rocky, AlmaLinux and CentOS
# take epel-release, RHEL CodeReady Builder and the EPEL release package. Any
# other system takes no step.
enable_epel() {
    [ -r "$1" ] || return 0
    release=$(
        # shellcheck disable=SC1090
        . "$1"
        echo "${ID:-} ${VERSION_ID:-}"
    )
    id=${release%% *}
    major=${release#* }
    major=${major%%.*}
    case "$id" in
        rocky | almalinux | centos)
            echo "Enabling CRB and EPEL, which the package's dependencies come from"
            $as_root dnf config-manager --set-enabled crb \
                && $as_root dnf install -y epel-release \
                || fail "EPEL could not be enabled; nothing was installed."
            ;;
        rhel)
            echo "Enabling CodeReady Builder and EPEL, which the package's dependencies come from"
            $as_root subscription-manager repos --enable "codeready-builder-for-rhel-$major-$(uname -m)-rpms" \
                && $as_root dnf install -y "$EPEL_RELEASE_PREFIX$major.noarch.rpm" \
                || fail "EPEL could not be enabled; nothing was installed."
            ;;
    esac
}

# What this script's edition's file names hold before the extension.
edition_suffix() {
    if [ "$EDITION" = cn ]; then
        echo "-cn"
    fi
}

# The pattern SHA256SUMS names the package by, with any version.
asset_pattern() {
    component=$1
    kind=$2
    machine=$3
    suffix=$(edition_suffix)
    case "$kind" in
        macos) echo "neutrino-$component-[0-9][^ ]*-macos-$machine$suffix\\.pkg" ;;
        deb) echo "neutrino-${component}_[0-9][^_ ]*_$machine$suffix\\.deb" ;;
        rpm)
            if [ "$machine" = amd64 ]; then
                rpm_machine=x86_64
            else
                rpm_machine=aarch64
            fi
            echo "neutrino-$component-[0-9][^ ]*-1\\.$rpm_machine$suffix\\.rpm"
            ;;
        arch)
            [ "$machine" = amd64 ] || return 1
            echo "neutrino-$component-[0-9][^ ]*-1-x86_64$suffix\\.pkg\\.tar\\.zst"
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

# The host of an address, which names its site to a person.
host_of() {
    echo "$1" | sed -E 's|^[a-z]+://([^/]+).*|\1|'
}

# Why curl failed, as every download names it: its exit code, then what it
# wrote out of the HTTP status.
failure_reason() {
    case "$1" in
        6 | 7) echo unreachable ;;
        22) echo "http_$2" ;;
        28) echo "$3" ;;
        33) echo http_200 ;;
        *) echo unreachable ;;
    esac
}

# Each site's address of the release's files, one per line.
site_bases() {
    # shellcheck disable=SC2086
    set -- $RELEASE_SITES
    while [ "$#" -ge 2 ]; do
        echo "${1%%"{tag}"*}$tag${1#*"{tag}"}"
        shift 2
    done
}

# The latest release's tag: every site's latest.json read at once, each for
# at most PROBE_WAIT_S, and the fastest answer naming a tag taken.
latest_tag() {
    read_dir="$work/latest"
    mkdir -p "$read_dir"
    read_pids=""
    read_index=0
    # shellcheck disable=SC2086
    set -- $RELEASE_SITES
    while [ "$#" -ge 2 ]; do
        read_index=$((read_index + 1))
        echo "$2" >"$read_dir/$read_index.url"
        (
            read_code=0
            curl -fsSL --max-time "$PROBE_WAIT_S" -o "$read_dir/$read_index.json" \
                -w '%{http_code} %{time_total}' "$2" >"$read_dir/$read_index.out" \
                2>/dev/null || read_code=$?
            echo " $read_code" >>"$read_dir/$read_index.out"
        ) &
        read_pids="$read_pids $!"
        shift 2
    done
    # shellcheck disable=SC2086
    wait $read_pids
    read_found=""
    read_reasons=""
    for read_out in "$read_dir"/*.out; do
        read_base=${read_out%.out}
        read -r read_status read_time read_code <"$read_out"
        read_host=$(host_of "$(cat "$read_base.url")")
        read_tag=""
        if [ "$read_code" = 0 ]; then
            read_tag=$(sed -n -E 's/.*"tag"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' \
                "$read_base.json" | head -n 1)
            [ -n "$read_tag" ] || read_reasons="$read_reasons, $read_host (no_tag)"
        else
            read_reasons="$read_reasons, $read_host ($(failure_reason "$read_code" "$read_status" timeout))"
        fi
        if [ -n "$read_tag" ]; then
            read_found="$read_found$read_time $read_tag
"
        fi
    done
    read_tag=$(printf '%s' "$read_found" | sort -n | head -n 1 | cut -d ' ' -f 2)
    [ -n "$read_tag" ] \
        || fail "No release site named the latest release: ${read_reasons#, }."
    echo "$read_tag"
}

# The sites serving one file, fastest first: every site probed at once for
# the file's first PROBE_BYTES, each for at most PROBE_WAIT_S. A site that
# answered is ranked by its speed from the first byte to the last, two
# speeds within a tenth of each other going to the earlier first byte; a
# site that did not answer in time comes after them; a site that failed is
# left out, and its reason added to $work/reasons.
rank_sites() {
    probe_dir="$work/probes"
    rm -rf "$probe_dir"
    mkdir -p "$probe_dir"
    probe_pids=""
    probe_index=0
    for probe_base in $(site_bases); do
        probe_index=$((probe_index + 1))
        echo "$probe_base" >"$probe_dir/$probe_index.base"
        (
            probe_code=0
            curl -sL -r "0-$((PROBE_BYTES - 1))" --max-time "$PROBE_WAIT_S" -o /dev/null \
                -w '%{http_code} %{size_download} %{time_starttransfer} %{time_total}' \
                "$probe_base$1" >"$probe_dir/$probe_index.out" 2>/dev/null \
                || probe_code=$?
            echo " $probe_code" >>"$probe_dir/$probe_index.out"
        ) &
        probe_pids="$probe_pids $!"
    done
    # shellcheck disable=SC2086
    wait $probe_pids
    : >"$probe_dir/answered"
    : >"$probe_dir/late"
    for probe_out in "$probe_dir"/*.out; do
        probe_base=$(cat "${probe_out%.out}.base")
        read -r probe_status probe_size probe_start probe_total probe_code <"$probe_out"
        case "$probe_status" in
            200 | 206) ;;
            000)
                if [ "$probe_code" = 28 ]; then
                    echo "$probe_base" >>"$probe_dir/late"
                else
                    echo "$(host_of "$probe_base") ($(failure_reason "$probe_code" "$probe_status" timeout))" \
                        >>"$work/reasons"
                fi
                continue
                ;;
            *)
                echo "$(host_of "$probe_base") (http_$probe_status)" >>"$work/reasons"
                continue
                ;;
        esac
        echo "$probe_size $probe_start $probe_total $probe_base" >>"$probe_dir/answered"
    done
    awk '
        function before(a, b) {
            if (speed[a] > speed[b] * 1.1) return 1
            if (speed[b] > speed[a] * 1.1) return 0
            return start[a] < start[b]
        }
        {
            span = $3 - $2
            if (span < 0.001) span = 0.001
            speed[NR] = $1 / span
            start[NR] = $2
            base[NR] = $4
            order[NR] = NR
        }
        END {
            for (i = 2; i <= NR; i++) {
                for (j = i; j > 1 && before(order[j], order[j - 1]); j--) {
                    kept = order[j]
                    order[j] = order[j - 1]
                    order[j - 1] = kept
                }
            }
            for (i = 1; i <= NR; i++) print base[order[i]]
        }
    ' "$probe_dir/answered"
    cat "$probe_dir/late"
}

# Download one file into the work directory from the fastest site, moving to
# the next site on a stall or an error and resuming where the last one
# stopped. Given a digest, a file that does not match it drops that site and
# is fetched again from the next one. Stops the script, naming each site and
# why it failed, when no site serves the file.
fetch_file() {
    fetch_target="$work/$1"
    rm -f "$fetch_target"
    : >"$work/reasons"
    for fetch_base in $(rank_sites "$1"); do
        fetch_host=$(host_of "$fetch_base")
        fetch_code=0
        fetch_status=$(curl -fsSL -C - --connect-timeout "$PROBE_WAIT_S" \
            --speed-limit 1 --speed-time "$STALL_S" -o "$fetch_target" \
            -w '%{http_code}' "$fetch_base$1" 2>/dev/null) || fetch_code=$?
        if [ "$fetch_code" != 0 ]; then
            echo "$fetch_host ($(failure_reason "$fetch_code" "$fetch_status" stalled))" \
                >>"$work/reasons"
            continue
        fi
        if [ -n "${2:-}" ] && [ "$(sha256_of "$fetch_target")" != "$2" ]; then
            echo "$fetch_host (digest_mismatch)" >>"$work/reasons"
            rm -f "$fetch_target"
            continue
        fi
        echo "Downloaded $1 from $fetch_host"
        return 0
    done
    fail "No release site served $1: $(paste -s -d ',' "$work/reasons" | sed 's/,/, /g')."
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

# Whether the hub on this machine has been set up: its panel settings hold a
# password hash, which is any value but the example's placeholder.
hub_is_set_up() {
    $as_root ${as_root:+-n} grep -Eq '"admin_password_hash"[[:space:]]*:[[:space:]]*"[^"]' "$1" 2>/dev/null \
        && ! $as_root ${as_root:+-n} grep -Eq '"admin_password_hash"[[:space:]]*:[[:space:]]*"PLACEHOLDER' "$1" 2>/dev/null
}

# The home of the person running the script, also when it runs through
# sudo.
person_home() {
    if [ "$(id -u)" != 0 ] || [ -z "${SUDO_USER:-}" ]; then
        echo "$HOME"
    elif command -v getent >/dev/null 2>&1; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory 2>/dev/null \
            | sed -n 's/^NFSHomeDirectory: //p'
    fi
}

# Whether the person running the script holds a client binding.
is_client_bound() {
    home=$(person_home)
    [ -n "$home" ] || return 1
    if [ "$1" = macos ]; then
        bindings="$home/$CLIENT_BINDINGS_MACOS"
    elif [ -n "${XDG_CONFIG_HOME:-}" ] && [ -z "${SUDO_USER:-}" ]; then
        bindings="$XDG_CONFIG_HOME/${CLIENT_BINDINGS_LINUX#.config/}"
    else
        bindings="$home/$CLIENT_BINDINGS_LINUX"
    fi
    grep -Eq '"token"[[:space:]]*:[[:space:]]*"[^"]' "$bindings" 2>/dev/null
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
    if [ -z "${NEUTRINO_ASSET_DIR:-}" ] && [ -z "$RELEASE_SITES" ]; then
        fail "This script names no release site; take it from a release, or set NEUTRINO_ASSET_DIR."
    fi

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
        tag=${NEUTRINO_VERSION:-}
        if [ -z "$tag" ]; then
            tag=$(latest_tag) || exit 1
        fi
        source_dir=$work
        fetch_file SHA256SUMS
    fi

    found=$(find_asset "$source_dir/SHA256SUMS" "$pattern")
    [ -n "$found" ] \
        || fail "The release publishes no Neutrino $component package for $kind on $machine."
    expected=${found%% *}
    name=${found#* }
    if [ -z "${NEUTRINO_ASSET_DIR:-}" ]; then
        fetch_file "$name" "$expected"
    fi
    package="$source_dir/$name"
    [ -f "$package" ] || fail "There is no $name in $source_dir."
    [ -z "${NEUTRINO_ASSET_DIR:-}" ] || echo "Found $name in $source_dir"
    [ "$(sha256_of "$package")" = "$expected" ] \
        || fail "$name does not match its SHA256SUMS line; nothing was installed."
    echo "$name matches its SHA256SUMS line"
    case "$package" in
        /*) ;;
        *) package="$(pwd)/$package" ;;
    esac

    [ "$kind" != rpm ] || enable_epel "$OS_RELEASE"
    echo "Installing $name"
    case "$kind" in
        macos) $as_root installer -pkg "$package" -target / ;;
        deb) $as_root apt-get install -y "$package" ;;
        rpm) $as_root dnf install -y "$package" ;;
        arch) $as_root pacman -U --noconfirm "$package" ;;
    esac
    echo "Installed $name"

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
            is_client_bound "$kind" && return 0
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
    if hub_is_set_up "$settings"; then
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
