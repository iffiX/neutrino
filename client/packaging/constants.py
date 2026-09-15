"""What every client package holds to, whatever format it is built as.

Pins of what the build fetches live beside the download that reads them; what
is here is what the project has decided about the machines a package installs
on.
"""

# The oldest glibc a Linux client package runs on. The client is the one
# package that compiles C in its container, so its binaries take the symbol
# versions of whatever glibc that container has; this is the line the
# container is chosen to stay under, and the build reads every ELF in its own
# tree against it.
PACKAGING_GLIBC_FLOOR = "2.34"
