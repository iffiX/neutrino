"""What the project names its package files and its machines.

The build scripts read these tables. A running hub learns the one name it
needs from the stamp its build writes into ``neutrino_hub/_version.py``.
"""

# The file each format writes, and so the name the hub asks a release for
# when it updates itself. `name` is the package, `version` the release,
# `architecture` the machine as that format spells it.
PACKAGING_ASSET_PATTERNS = {
    "deb": "{name}_{version}_{architecture}.deb",
    "rpm": "{name}-{version}-1.{architecture}.rpm",
    "pkg": "{name}-{version}-1-{architecture}.pkg.tar.zst",
    "msi": "{name}-{version}-windows-{architecture}.msi",
    "macos_pkg": "{name}-{version}-macos-{architecture}.pkg",
}

# The name each family gives the same machine.
PACKAGING_ARCHITECTURE_NAMES = {
    "amd64": {"debian": "amd64", "rhel": "x86_64", "arch": "x86_64"},
    "arm64": {"debian": "arm64", "rhel": "aarch64", "arch": "aarch64"},
}

# The two editions, and the file at the root of a tree naming its own.
PACKAGING_EDITIONS = ("intl", "cn")
PACKAGING_EDITION_FILE = "EDITION"

# Every repository path that exists for a feature the mainland edition `cn`
# leaves out, the proxy and NetBird, and for nothing else: its packages, their
# mirrored tests, its frontend files, its examples and unit templates, and the
# scripts that build its programs. Deleting these from the tree is the whole of
# what makes the mainland tree. The one list of what `cn` leaves out.
PACKAGING_CN_LEFT_OUT_PATHS = (
    # The hub: the proxy.
    "hub/neutrino_hub/modules/xray",
    "hub/neutrino_hub/modules/tun",
    "hub/neutrino_hub/web/routers/hub/proxy.py",
    "hub/neutrino_hub/web/routers/hub/proxy_node.py",
    "hub/neutrino_hub/data/examples/xray",
    "hub/neutrino_hub/data/services/neutrino_hub_xray.service",
    "hub/tests/modules/xray",
    "hub/tests/modules/tun",
    "hub/tests/web/routers/hub/test_proxy.py",
    "hub/tests/web/routers/hub/test_proxy_node.py",
    "licenses/xray_core.txt",
    "licenses/v2fly_geoip.txt",
    "licenses/v2fly_domain_list_community.txt",
    # The hub: NetBird.
    "hub/neutrino_hub/modules/netbird",
    "hub/neutrino_hub/web/routers/hub/overlay_netbird.py",
    "hub/neutrino_hub/data/examples/netbird",
    "hub/neutrino_hub/data/services/neutrino_hub_netbird.service",
    "hub/tests/modules/netbird",
    "hub/tests/web/routers/hub/test_overlay_netbird.py",
    "licenses/netbird.txt",
    # The panel: the Proxy page and the panels only it shows.
    "hub/frontend/src/pages/proxy_page.tsx",
    "hub/frontend/src/pages/proxy_page.css",
    "hub/frontend/src/components/nodes_panel.tsx",
    "hub/frontend/src/components/nodes_panel.css",
    "hub/frontend/src/components/node_card.tsx",
    "hub/frontend/src/components/node_card.css",
    "hub/frontend/src/node_draft.ts",
    "hub/frontend/src/components/geodata_panel.tsx",
    "hub/frontend/src/components/geodata_panel.css",
    "hub/frontend/src/components/socks_ports_panel.tsx",
    "hub/frontend/src/components/socks_ports_panel.css",
    # The panel: NetBird's card on the Access page.
    "hub/frontend/src/components/netbird_card.tsx",
    "hub/frontend/src/components/netbird_card.css",
    # The desktop client: NetBird and the daemon that runs it.
    "client/desktop/neutrino_client/netbird",
    "client/desktop/neutrino_client/data/services/neutrino_client_netbird.service",
    "client/desktop/frontend/parts/netbird.js",
    "client/desktop/packaging/netbird_payload.py",
    "client/desktop/tests/netbird",
    "client/desktop/tests/packaging/test_netbird_payload.py",
    # The Android app: the NetBird core and the script that builds it.
    "client/android/app/src/netbird",
    "client/android/app/src/test_netbird",
    "packaging/build/build_core_netbird.py",
)

# The released packages a Windows check installs first, so the package it
# checks goes on over an earlier version as an upgrade does: each target's
# asset and its hash. The agent's 0.4.0 ran upstream's RustDesk installer,
# which an upgrade takes away. The hub has no Windows package before 0.5.0.
PACKAGING_EARLIER_RELEASE_URL = (
    "https://github.com/iffiX/neutrino/releases/download/v{version}/{asset}"
)
PACKAGING_EARLIER_VERSION = "0.4.0"
PACKAGING_EARLIER_PACKAGES = {
    "agent_windows": (
        "neutrino-agent-0.4.0-windows-amd64.msi",
        "db3e80e662c1dcde0d3f88f4a47d7ad96be2d74f1af3ad5549bac81376ebf455",  # scan: allow
    ),
    "client_windows": (
        "neutrino-client-0.4.0-windows-amd64.msi",
        "550215b28ba9980f7b681d48ad388758d258e88256a11c212dd3acd977473374",  # scan: allow
    ),
}

# tun2socks, which the hub's macOS and Windows packages carry for the
# proxy's TUN and the client's Windows package carries for its files adapter
# in both editions: the release, the asset each system and machine takes and
# its hash, the program's name inside each archive, and its licence under
# licenses/. A hub learns the version only from its _version.py stamp.
PACKAGING_TUN2SOCKS_VERSION = "2.7.0"
PACKAGING_TUN2SOCKS_RELEASE_URL = (
    "https://github.com/xjasonlyu/tun2socks/releases/download/v{version}/{asset}"
)
PACKAGING_TUN2SOCKS_ASSETS = {
    ("darwin", "amd64"): (
        "tun2socks-darwin-amd64.zip",
        "6e654da8bab9ca1645862f0e251a69980e0966680713011feea7b1e5901b2a95",  # scan: allow
    ),
    ("darwin", "arm64"): (
        "tun2socks-darwin-arm64.zip",
        "7c5ebfe2ffb60ecf6e958cc5bbf3e06e74b8b33575ffbb4ba4f6f785a647f1ad",  # scan: allow
    ),
    ("windows", "amd64"): (
        "tun2socks-windows-amd64.zip",
        "c5d46e9452f6c9cc7c15ab9158d6d6a0169ceecd6bca019ce476b49337d2be43",  # scan: allow
    ),
}
PACKAGING_TUN2SOCKS_ASSET_MEMBER = "tun2socks-{os_name}-{machine}"
PACKAGING_TUN2SOCKS_LICENSE = "tun2socks.txt"

# The cc-switch CLI, which every client package carries for the person's AI
# tools in both editions, and which the hub offers its agents at the same
# version when their AI tools are used: the release, the asset each system
# and machine takes and its hash (machines named as the interpreter releases name them;
# the musl builds on Linux need nothing of the machine's C library), the
# program's name inside each archive, and its licence under licenses/.
PACKAGING_CC_SWITCH_VERSION = "5.10.4"
PACKAGING_CC_SWITCH_URL = (
    "https://github.com/SaladDay/cc-switch-cli/releases/download/"
    "v{version}/cc-switch-cli-v{version}-{asset}"
)
PACKAGING_CC_SWITCH_ASSETS = {
    ("linux", "x86_64"): (
        "linux-x64-musl.tar.gz",
        "a9a569d85cb0a61169082a558f86786e0e7ee9c2725900e7d6e876873eb416c3",  # scan: allow
    ),
    ("linux", "aarch64"): (
        "linux-arm64-musl.tar.gz",
        "37d9b2564f9d47215dbb45914158d71f746d92d829ad62ca1214de4eeb5bfc6f",  # scan: allow
    ),
    ("windows", "x86_64"): (
        "windows-x64.zip",
        "6bc4ceea645cdf3cebc662e859d6a8804e3a3c737d4968497f66ba6df481f1a7",  # scan: allow
    ),
    ("darwin", "aarch64"): (
        "darwin-arm64.tar.gz",
        "7ca345ac2c9c930e7929252584fcfe7e7507ae40c1350d4969a80bafbad769f5",  # scan: allow
    ),
    ("darwin", "x86_64"): (
        "darwin-x64.tar.gz",
        "aaea1f60f5d34b784831c9a6cb9568927a07930e52fd295608b94d2ac17ba53b",  # scan: allow
    ),
}
PACKAGING_CC_SWITCH_BINARY_NAME = "cc-switch"
PACKAGING_CC_SWITCH_WINDOWS_BINARY_NAME = "cc-switch.exe"
PACKAGING_CC_SWITCH_LICENSE = "cc_switch.txt"

# The line naming the edition in each one-command install script, which the
# mainland source tree stamps `cn`.
PACKAGING_INSTALL_EDITION_LINES = {
    "packaging/install/install.sh": 'EDITION="{edition}"',
    "packaging/install/install.ps1": "$script:NeutrinoEdition = '{edition}'",
}

# The variable a build in a container reads its edition from.
PACKAGING_EDITION_ENV = "NEUTRINO_EDITION"

# The mainland release's repository on Gitee, where its API is, where the
# tree is pushed, and the SSH host key gitee.com publishes, which the push
# is checked against.
PACKAGING_GITEE_REPOSITORY = "iffiX/neutrino"
PACKAGING_GITEE_API = "https://gitee.com/api/v5"
PACKAGING_GITEE_PUSH_URL = "git@gitee.com:iffiX/neutrino.git"
PACKAGING_GITEE_SSH_HOST_KEY = (
    "gitee.com ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIEKxHSJ7084RmkJ4YdEi5tngynE8aZe2uEoVVsB/OvYN"  # scan: allow
)

# Gitee's limits in bytes: one release attachment, all attachments of the
# repository, one file in the repository, and the repository's git data.
PACKAGING_GITEE_ATTACHMENT_BYTES_MAX = 100_000_000
PACKAGING_GITEE_ATTACHMENTS_BYTES_MAX = 1_000_000_000
PACKAGING_GITEE_FILE_BYTES_MAX = 50_000_000
PACKAGING_GITEE_REPOSITORY_BYTES_MAX = 500_000_000
