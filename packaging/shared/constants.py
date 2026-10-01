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
}

# The name each family gives the same machine.
PACKAGING_ARCHITECTURE_NAMES = {
    "amd64": {"debian": "amd64", "rhel": "x86_64", "arch": "x86_64"},
    "arm64": {"debian": "arm64", "rhel": "aarch64", "arch": "aarch64"},
}
