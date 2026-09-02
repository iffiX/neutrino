from pathlib import Path

# Arrives through the package manager, which picks the machine's build.
PODMAN_SUPPORTED_ARCHITECTURES = ("*",)

# podman-docker adds a `docker` alias over podman, so hands and scripts that
# speak docker keep working unchanged. Every family spells both the same.
PODMAN_PACKAGES = {
    "debian": ("podman", "podman-docker"),
    "rhel": ("podman", "podman-docker"),
    "arch": ("podman", "podman-docker"),
}

# Where Quadlet arrives, which is a question about which files this machine's
# podman reads — not about whether podman is worth installing. From 4.4 a
# rendered .container file becomes a unit; below it that file is inert, so
# `PodmanUnitRenderer` writes plain .service units running `podman run`
# instead and the containers work either way. Debian 12 ships 4.3.1 and
# Ubuntu 22.04 ships 3.4.4, backports included, so the older path is what
# those machines actually use.
PODMAN_QUADLET_VERSION = "4.4"

# Podman has no daemon; the API socket is the unit that stands for the engine
# on the Services page — present once installed, active when listening.
PODMAN_UNIT = "podman.socket"

# Units name the binary in full: systemd runs them with a minimal PATH.
PODMAN_BINARY = "/usr/bin/podman"

# Where a unit rendered for a podman without Quadlet lands. Quadlet's own
# output for <name>.container is called <name>.service too, so a container
# has one unit name whichever renderer produced it.
PODMAN_UNIT_DIR = Path("/etc/systemd/system")

# Where Quadlet reads declared containers from. Each rendered <name>.container
# becomes a systemd unit called <name>.service on the next daemon-reload.
PODMAN_QUADLET_DIR = Path("/etc/containers/systemd")

# The default rootful network's bridge. The firewall must let it forward, or
# the gateway's default-drop forward chain silently cuts every container off
# from the internet.
PODMAN_BRIDGE = "podman0"

# Images, container layers and named volumes all live here.
PODMAN_DATA_DIR = Path("/var/lib/containers")

# Where the docker.io mirror list lands. A drop-in, so the distribution's own
# registries.conf stays untouched.
PODMAN_REGISTRIES_CONF_PATH = Path(
    "/etc/containers/registries.conf.d/99_neutrino_mirrors.conf"
)
