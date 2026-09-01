#!/usr/bin/env bash
# The mini network the mode matrix runs against: one hub with three ports, one
# client on the wire the hub will serve.
#
#   setup_vms.sh <distro> <version> [prefix]
#
#   setup_vms.sh debian 12
#   setup_vms.sh ubuntu 24.04 mx
#
# Run on a libvirt host. Naming the distro and version is what pins a
# behaviour to a release: the image comes from the distribution's own cloud
# image for exactly that version, downloaded once and reused.
#
# What it builds:
#
#   <prefix>hub     three ports, in this order: the way in (libvirt's default
#                   NAT), a second uplink (neutrino-wan2, its own NAT), and a
#                   wire with nothing on it (neutrino-served) for the hub to
#                   serve. Only the first is configured by the image; the
#                   matrix gives the others their roles.
#   <prefix>client  one port on the served wire, asking DHCP forever. Nobody
#                   answers until the hub serves, and its lease is the
#                   end-to-end signal that serving works.
#
# The hub is driven through the QEMU guest agent (vm_exec.py), which survives
# everything the tests do to its network.
set -euo pipefail
export LIBVIRT_DEFAULT_URI="qemu:///system"

DISTRO="${1:?usage: setup_vms.sh <distro> <version> [prefix]}"
VERSION="${2:?usage: setup_vms.sh <distro> <version> [prefix]}"
PREFIX="${3:-nmx}"
LAB="${NEUTRINO_VM_LAB:-$HOME/.local/share/neutrino_vm_lab}"
HERE="$(cd "$(dirname "$0")" && pwd)"
MEMORY_MB=3072
CPUS=2

mkdir -p "$LAB/images" "$LAB/disks" "$LAB/seeds"

# --- the image, pinned to the version that was named -------------------------

IMAGE="$DISTRO$(echo "$VERSION" | tr -d .)"
image_url() {
    case "$DISTRO/$VERSION" in
        debian/11) echo "https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-genericcloud-amd64.qcow2" ;;  # scan: allow
        debian/12) echo "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2" ;;  # scan: allow
        debian/13) echo "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2" ;;  # scan: allow
        ubuntu/22.04) echo "https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img" ;;  # scan: allow
        ubuntu/24.04) echo "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img" ;;  # scan: allow
        fedora/42) echo "https://download.fedoraproject.org/pub/fedora/linux/releases/42/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-42-1.1.x86_64.qcow2" ;;  # scan: allow
        alma/9) echo "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2" ;;  # scan: allow
        rocky/9) echo "https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2" ;;  # scan: allow
        arch/rolling) echo "https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2" ;;  # scan: allow
        *) echo "" ;;
    esac
}

BASE="$LAB/images/$IMAGE.qcow2"
if [ ! -f "$BASE" ]; then
    URL="$(image_url)"
    if [ -z "$URL" ]; then
        echo "no image for $DISTRO $VERSION and no URL known for it" >&2
        echo "have: $(ls "$LAB/images" 2>/dev/null | sed 's/.qcow2//' | tr '\n' ' ')" >&2
        exit 1
    fi
    echo "fetching $DISTRO $VERSION ..."
    curl -fL --progress-bar -o "$BASE.part" "$URL"
    mv "$BASE.part" "$BASE"
fi

# --- the wires ---------------------------------------------------------------

ensure_network() {
    name="$1"; xml="$2"
    virsh net-info "$name" >/dev/null 2>&1 && return 0
    echo "$xml" > "$LAB/seeds/$name.xml"
    virsh net-define "$LAB/seeds/$name.xml" >/dev/null
    virsh net-autostart "$name" >/dev/null
    virsh net-start "$name" >/dev/null
}

# A second way to the internet, so a router has something to balance across.
ensure_network neutrino-wan2 "<network>
  <name>neutrino-wan2</name>
  <forward mode='nat'/>
  <bridge name='virbr-nwan2' stp='on' delay='0'/>
  <ip address='192.168.124.1' netmask='255.255.255.0'>
    <dhcp><range start='192.168.124.50' end='192.168.124.200'/></dhcp>
  </ip>
</network>"

# A wire with nothing on it at all: no address, no DHCP, no way out. Whatever
# answers here is the hub under test, and nothing else can take the credit.
ensure_network neutrino-served "<network>
  <name>neutrino-served</name>
  <bridge name='virbr-nsrv' stp='on' delay='0'/>
</network>"

# --- the machines ------------------------------------------------------------

KEY="$LAB/id_lab"
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -f "$KEY"

packages_for() {
    case "$IMAGE" in
        fedora*) echo "qemu-guest-agent python3-pip" ;;
        arch*)   echo "qemu-guest-agent python-pip" ;;
        *)       echo "qemu-guest-agent python3-venv python3-pip" ;;
    esac
}

seed_for() {
    name="$1"; is_provisioned="$2"
    {
        echo "#cloud-config"
        echo "users:"
        echo "  - name: lab"
        echo "    sudo: ALL=(ALL) NOPASSWD:ALL"
        echo "    shell: /bin/bash"
        echo "    ssh_authorized_keys:"
        echo "      - $(cat "$KEY.pub")"
        echo "ssh_pwauth: false"
        if [ "$is_provisioned" = yes ]; then
            echo "package_update: true"
            echo "packages:"
            for package in $(packages_for); do echo "  - $package"; done
            echo "runcmd:"
            echo "  - [systemctl, enable, --now, qemu-guest-agent]"
            # The RHEL family ships the agent confined and with guest-exec
            # off; a throwaway box under network tests needs the channel more
            # than the confinement.
            case "$IMAGE" in
                fedora*|rocky*|alma*|centos*)
                    echo "  - [setenforce, '0']"
                    echo "  - [sed, -i, 's/^SELINUX=enforcing/SELINUX=permissive/', /etc/selinux/config]"
                    echo "  - [sed, -i, 's/^BLACKLIST_RPC=.*/BLACKLIST_RPC=/', /etc/sysconfig/qemu-ga]"
                    echo "  - [systemctl, restart, qemu-guest-agent]"
                    ;;
            esac
        fi
    } > "$LAB/seeds/$name.user-data"
    printf 'instance-id: %s\nlocal-hostname: %s\n' "$name" "$name" \
        > "$LAB/seeds/$name.meta-data"
    cloud-localds "$LAB/seeds/$name.iso" \
        "$LAB/seeds/$name.user-data" "$LAB/seeds/$name.meta-data"
}

boot() {
    name="$1"; is_provisioned="$2"; shift 2
    virsh destroy "$name" >/dev/null 2>&1 || true
    virsh undefine "$name" --remove-all-storage >/dev/null 2>&1 || true
    rm -f "$LAB/disks/$name.qcow2"
    qemu-img create -q -f qcow2 -F qcow2 -b "$BASE" "$LAB/disks/$name.qcow2" 20G
    seed_for "$name" "$is_provisioned"
    virt-install --name "$name" --memory "$MEMORY_MB" --vcpus "$CPUS" \
        --disk "$LAB/disks/$name.qcow2",device=disk,bus=virtio \
        --disk "$LAB/seeds/$name.iso",device=cdrom \
        --os-variant linux2022 "$@" \
        --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
        --graphics none --noautoconsole --import >/dev/null
}

HUB="${PREFIX}hub"
CLIENT="${PREFIX}client"

echo "booting $HUB ($DISTRO $VERSION): way in, second uplink, served wire"
boot "$HUB" yes \
    --network network=default,model=virtio \
    --network network=neutrino-wan2,model=virtio \
    --network network=neutrino-served,model=virtio

# The client needs no internet and no agent: it exists to keep asking for a
# lease on a wire where only the hub can ever answer.
echo "booting $CLIENT ($DISTRO $VERSION): one port on the served wire"
boot "$CLIENT" no --network network=neutrino-served,model=virtio

printf 'waiting for %s' "$HUB"
for _ in $(seq 300); do
    if python3 "$HERE/vm_exec.py" "$HUB" 'command -v cloud-init >/dev/null' >/dev/null 2>&1; then
        # The agent answers before cloud-init has installed everything; ready
        # means the package list has been worked through.
        if python3 "$HERE/vm_exec.py" "$HUB" 'cloud-init status --wait >/dev/null 2>&1; command -v python3 >/dev/null' >/dev/null 2>&1; then
            break
        fi
    fi
    printf .
    sleep 2
done
echo

echo "the mini network:"
echo "  $HUB      hub under test; drive it with: python3 $HERE/vm_exec.py $HUB '<command>'"
echo "  $CLIENT   client on the served wire, asking DHCP until the hub answers"
echo
echo "next:"
echo "  python3 $HERE/vm_exec.py $HUB 'mkdir -p /opt/integration'"
echo "  for f in $HERE/*.py $HERE/*.sh $HERE/pytest.ini; do python3 $HERE/vm_exec.py $HUB push \$f /opt/integration/\$(basename \$f); done"
echo "  python3 $HERE/vm_exec.py $HUB push <package.deb> /tmp/<package.deb>"
echo "  python3 $HERE/vm_exec.py $HUB 'bash /opt/integration/run_mode_matrix.sh /tmp/<package.deb> --client'"
