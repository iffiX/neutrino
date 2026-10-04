#!/usr/bin/env bash
# A lab VM standing in for the owner's VPS, the server the relay forwards
# through.
#
#   make_vps.sh <relay public key file> [name]
#
#   make_vps.sh /root/relay_key.pub
#
# Run on the libvirt host, after setup_vms.sh has fetched the Debian 12 image.
# Building it again deletes the VM of the same name first.
#
# What it builds:
#
#   <name> (nmxvps)  one port on neutrino-wan2, where the workstation and the
#                    emulators reach it, and one macvtap on the host's wired
#                    interface, where the lab hubs reach it. Two accounts:
#                    `lab`, with sudo and the lab key, for the tester; and
#                    `relay`, holding the relay's public key, for the hub.
#                    sshd takes `GatewayPorts clientspecified`, as
#                    docs/guide/hub/relay.md has the owner set it.
#
# The relay account's key carries no `permitlisten` option here, so one VM
# serves any public port the tests pick (18443 to 18499).
set -euo pipefail
export LIBVIRT_DEFAULT_URI="qemu:///system"

RELAY_PUB="${1:?usage: make_vps.sh <relay public key file> [name]}"
NAME="${2:-nmxvps}"
LAB="${NEUTRINO_VM_LAB:-/var/lib/neutrino_vm_lab}"
WIRED="${NEUTRINO_VM_WIRED:-enp5s0}"
BASE="$LAB/images/debian12.qcow2"
WAN_MAC=52:54:00:a5:00:01
LAN_MAC=52:54:00:a5:00:02

if [ ! -f "$BASE" ]; then
    echo "no Debian 12 image at $BASE; run setup_vms.sh debian 12 first" >&2
    exit 1
fi
mkdir -p "$LAB/disks" "$LAB/seeds"

virsh destroy "$NAME" >/dev/null 2>&1 || true
virsh undefine "$NAME" --remove-all-storage >/dev/null 2>&1 || true
rm -f "$LAB/disks/$NAME.qcow2"
qemu-img create -q -f qcow2 -F qcow2 -b "$BASE" "$LAB/disks/$NAME.qcow2" 8G

cat > "$LAB/seeds/$NAME.user-data" <<UD
#cloud-config
users:
  - name: lab
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$LAB/id_lab.pub")
  - name: relay
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$RELAY_PUB")
ssh_pwauth: false
write_files:
  - path: /etc/ssh/sshd_config.d/10-relay.conf
    content: |
      GatewayPorts clientspecified
      ClientAliveInterval 30
packages:
  - qemu-guest-agent
runcmd:
  - [systemctl, enable, --now, qemu-guest-agent]
  - [systemctl, restart, ssh]
UD
printf 'instance-id: %s\nlocal-hostname: %s\n' "$NAME" "$NAME" > "$LAB/seeds/$NAME.meta-data"
cat > "$LAB/seeds/$NAME.network-config" <<NC
version: 2
ethernets:
  wan:
    match: {macaddress: "$WAN_MAC"}
    dhcp4: true
  lan:
    match: {macaddress: "$LAN_MAC"}
    dhcp4: true
    dhcp4-overrides: {use-routes: false, use-dns: false}
NC
cloud-localds --network-config "$LAB/seeds/$NAME.network-config" \
    "$LAB/seeds/$NAME.iso" "$LAB/seeds/$NAME.user-data" "$LAB/seeds/$NAME.meta-data"

virt-install --name "$NAME" --memory 1024 --vcpus 1 \
    --disk "$LAB/disks/$NAME.qcow2,device=disk,bus=virtio" \
    --disk "$LAB/seeds/$NAME.iso,device=disk,bus=virtio" \
    --os-variant linux2022 \
    --network "network=neutrino-wan2,model=virtio,mac=$WAN_MAC" \
    --network "type=direct,source=$WIRED,source_mode=bridge,model=virtio,mac=$LAN_MAC" \
    --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
    --graphics none --noautoconsole --import >/dev/null
echo "$NAME started; its addresses: virsh domifaddr $NAME --source agent"
