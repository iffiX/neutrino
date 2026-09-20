"""What every hub package holds to, whatever format it is built as.

Pins of what the build fetches live beside the download that reads them; what
is here is what the project has decided about the machines a package installs
on.
"""

# The oldest glibc a hub package runs on. Measured rather than chosen: it is
# the highest version the compiled wheels in the carried environment name, and
# it sits under Ubuntu 22.04's 2.35, which is the floor the project declares.
# The build reads every ELF in its own tree against this.
PACKAGING_GLIBC_FLOOR = "2.34"

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
