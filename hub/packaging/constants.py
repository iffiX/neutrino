"""What every hub package holds to, whatever format it is built as.

Pins of what the build fetches live beside the download that reads them; what
is here is what the project has decided about the machines a package installs
on. The names of the package files and of the machines are in
``packaging/shared/constants.py``.
"""

# The oldest glibc a hub package runs on. Measured rather than chosen: it is
# the highest version the compiled wheels in the carried environment name, and
# it sits under Ubuntu 22.04's 2.35, which is the floor the project declares.
# The build reads every ELF in its own tree against this.
PACKAGING_GLIBC_FLOOR = "2.34"

# The hub's icon set under images/icons: the mark with the panel's accent edge
# and glow, told apart from the client's plain mark.
HUB_ICON_NAME = "neutrino_hub"

# How dpkg-deb compresses the mainland hub package: xz at its strongest.
HUB_DEB_CN_COMPRESSION = ("-Zxz", "-z9", "-Sextreme")
