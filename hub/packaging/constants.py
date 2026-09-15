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
