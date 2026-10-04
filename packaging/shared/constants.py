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
    # The hub: NetBird.
    "hub/neutrino_hub/modules/netbird",
    "hub/neutrino_hub/web/routers/hub/overlay_netbird.py",
    "hub/neutrino_hub/data/examples/netbird",
    "hub/neutrino_hub/data/services/neutrino_hub_netbird.service",
    "hub/tests/modules/netbird",
    "hub/tests/web/routers/hub/test_overlay_netbird.py",
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
    # The Android app: the NetBird core and the script that builds it.
)

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
