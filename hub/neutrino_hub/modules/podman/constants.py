from pathlib import Path

# Arrives through apt, which picks the machine's build.
PODMAN_SUPPORTED_ARCHITECTURES = ("*",)

# Podman has no daemon; the API socket is the unit that stands for the engine
# on the Services page — present once installed, active when listening.
PODMAN_UNIT = "podman.socket"

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
