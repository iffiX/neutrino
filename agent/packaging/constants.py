"""What every agent package holds to, whatever format it is built as.

Pins of what the build fetches live beside the download that reads them; what
is here is what the project has decided about the machines a package installs
on.
"""

# The oldest glibc an agent package runs on: the hub's packages' own floor, so
# one system runs both. The RustDesk host the package carries needs 2.27 and
# Codeg's binaries 2.34, both within it. The build reads every ELF in its own
# tree against this.
PACKAGING_GLIBC_FLOOR = "2.34"
