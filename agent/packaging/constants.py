"""What every agent package holds to, whatever format it is built as.

Pins of what the build fetches live beside the download that reads them; what
is here is what the project has decided about the machines a package installs
on.
"""

# The oldest glibc an agent package runs on. Measured rather than chosen: the
# RustDesk host the package carries needs 2.27, and the floor the project
# declares is Ubuntu 22.04's 2.35. The build reads every ELF in its own tree
# against this.
PACKAGING_GLIBC_FLOOR = "2.34"
