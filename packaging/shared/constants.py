"""What the project names its package files, its machines and its editions,
and where the mainland edition is released.

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

# The editions one tag builds, the first being what a build is when none is
# named, and the variable a build in a container reads its edition from.
PACKAGING_EDITIONS = ("intl", "cn")
PACKAGING_EDITION_ENV = "NEUTRINO_EDITION"

# Every repository path that exists for a feature the mainland edition
# leaves out.
PACKAGING_CN_LEFT_OUT_PATHS = ()

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
