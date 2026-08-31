"""Unit names, package lists, and paths the deployment depends on."""

from pathlib import Path

# Units the panel shows and controls. The key is what the panel displays; the
# value is the systemd unit behind it.
# The units without which this is not a gateway. Traffic does not move if any
# of them is down, so the panel shows their state and their logs but offers no
# way to stop them: a gateway with dnsmasq disabled is not a gateway with a
# feature turned off, it is a broken gateway.
SYSTEM_CORE_UNITS = {
    "xray": "xray.service",
    "router": "neutrino_router.service",
    "dnsmasq": "dnsmasq.service",
    "web": "neutrino_web.service",
    # The AI gateway: every machine's tools point at it, so taking it down
    # takes their AI away — same no-off-switch treatment as netbird.
    "cliproxyapi": "neutrino_cliproxyapi.service",
}

# What the box also happens to host because it is already there and always on.
# Each is off until asked for, and enabling one is what makes its page appear
# in the sidebar — so the panel stays as small as the appliance actually is.
SYSTEM_OPTIONAL_UNITS = {
    # Remote access: a LAN-shaped network over the wide one. A gateway routes,
    # resolves and serves without it, so it is a capability rather than a
    # premise — and it is AGPL-3.0, which is a licence about offering software
    # over a network. Installed from the vendor by the machine that wants it,
    # never carried in these packages.
    "netbird": "netbird.service",
    "samba": "smbd.service",
    "gitea": "gitea.service",
    # Podman has no daemon; its API socket stands for the engine here.
    "podman": "podman.socket",
    # The event daemon stands for ZFS: pools work without it, but it is the
    # monitorable part, and its presence is what puts the page in the sidebar.
    "zfs": "zfs-zed.service",
}

SYSTEM_MANAGED_UNITS = {**SYSTEM_CORE_UNITS, **SYSTEM_OPTIONAL_UNITS}

# What a provisioner can ask agreement for. The panel words each of these;
# nothing here or below it writes a sentence, so they can be translated and
# these stay facts.
SYSTEM_CONSENT_KERNEL_MODULE_BUILD = "kernel_module_build"
SYSTEM_CONSENT_THIRD_PARTY_REPOSITORY = "third_party_repository"

# What the hub itself cannot run without, installed by the package manager.
# The dependency field of every package is generated from this list, so the
# two cannot say different things; a checkout, which has no package to do it,
# installs the same list from `nhub setup`.
#
# Nothing an optional module needs belongs here. Each declares its own
# `<PREFIX>_PACKAGES` and installs it when the panel provisions it, and
# everything vendored (xray, the AI gateway, NetBird, Gitea) comes from its
# vendor because the distribution versions lag badly.
SYSTEM_RUNTIME_PACKAGES = (
    "nftables",
    "dnsmasq",
    "iproute2",
    # The router layer is 351 lines of nmcli; without it no interface has a
    # role and nothing routes.
    "network-manager",
    # Bans SSH brute-force sources at the firewall, on the same escalating
    # ladder the panel login uses. Configured by the installer's jail file.
    "fail2ban",
    # Reports what a radio can actually do. The panel asks it whether a Wi-Fi
    # card supports access-point mode before offering to serve a network on it.
    "iw",
    # The Devices page sweeps the LAN with it, and the traffic history reads
    # from vnstat.
    "arp-scan",
    "vnstat",
    # Provisioners that install from a vendor's own script fetch it with this.
    "curl",
)

# Wanted only by a machine that serves Wi-Fi, which is why it is a
# recommendation rather than a dependency. NetworkManager will not run the
# access point on our terms: its AP mode forces shared addressing, which
# starts a second dnsmasq that both holds port 53 and answers clients outside
# the proxy, so the gateway runs hostapd itself.
SYSTEM_WIFI_PACKAGES = ("hostapd",)

# Wanted by a checkout, which builds a virtual environment. A package carries
# its own interpreter and must never depend on the system's.
SYSTEM_CHECKOUT_PACKAGES = ("python3-venv",)

# Where a family spells one of the names above differently. A name absent from
# a family's entry keeps the name above; a name mapped to None is one that
# family has no separate package for, because it is already installed.
# Measured in containers on 2026-08-31, not inferred: every other name above
# is spelled the same on Debian, Fedora and Arch.
SYSTEM_PACKAGE_NAMES = {
    "debian": {},
    "rhel": {
        "iproute2": "iproute",
        "network-manager": "NetworkManager",
        # RHEL builds venv into the interpreter rather than splitting it out.
        "python3-venv": None,
    },
    "arch": {
        "network-manager": "networkmanager",
        "python3-venv": None,
    },
}

# The panel runs from a virtual environment inside the repo rather than from
# system packages: Ubuntu marks its Python externally managed, and an appliance
# should not have its dependencies changed out from under it by an apt upgrade.
SYSTEM_VENV_DIR_NAME = ".venv"

SYSTEM_XRAY_USER = "xray"

SYSTEM_SYSTEMD_DIR = Path("/etc/systemd/system")

# Where the installer writes fail2ban's policy, and the policy itself: five
# free failures, then bans that stretch from 30 seconds to a day — the same
# ladder as the panel login, but per source address, because one shared
# lockout would let anyone shut the owner out of their own box. The overlay
# range stays exempt: NetBird is the way back in and must never self-ban.
SYSTEM_FAIL2BAN_JAIL_PATH = Path("/etc/fail2ban/jail.d/neutrino.conf")
SYSTEM_FAIL2BAN_JAIL = """\
# Generated by neutrino. Do not edit; the installer owns it.
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
banaction = nftables-multiport
banaction_allports = nftables-allports
bantime = 30
bantime.increment = true
bantime.multipliers = 1 2 10 120 2880
ignoreip = 127.0.0.1/8 ::1 100.88.0.0/16
"""
