"""Making the declared containers true on the box, and reading what runs.

Declared containers live as Quadlet files and are driven through systemd;
containers someone started by hand at a shell are still listed and still
controllable, just through podman directly — the page shows one world either
way.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from neutrino_hub.system.package_manager import is_version_at_least
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.podman.config import PodmanConfig
from neutrino_hub.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_MINIMUM_VERSION,
    PODMAN_QUADLET_DIR,
    PODMAN_REGISTRIES_CONF_PATH,
    PODMAN_UNIT_DIR,
)
from neutrino_hub.modules.podman.renderer import (
    GENERATED_MARKER,
    PodmanQuadletRenderer,
    PodmanUnitRenderer,
)

CONTAINER_ACTIONS = ("start", "stop", "restart")


@dataclass
class PodmanContainerState:
    """One container as podman sees it right now.

    Attributes:
        name: The container's name.
        image: The image it runs.
        status: Podman's own words, for example ``Up 2 hours``.
        is_running: Whether it is running.
        is_declared: Whether config/ declares it — the page separates what
            the gateway owes a restart from what a shell left behind.
    """

    name: str
    image: str
    status: str
    is_running: bool
    is_declared: bool


class PodmanUnitApplier:
    """Installs rendered container units and reconciles systemd with them.

    Where the files go and what they are called depends on whether this
    machine's podman reads Quadlet; :func:`container_applier` decides that and
    builds this. Everything after the write is the same either way, because a
    container's unit is called ``<name>.service`` on both paths.
    """

    def __init__(self, *, directory: Path, suffix: str):
        """Hold where the rendered files belong.

        Args:
            directory: Where the files are written.
            suffix: What the rendered files are called, ``.container`` for
                Quadlet and ``.service`` without it.
        """
        self._directory = directory
        self._suffix = suffix

    @property
    def directory(self) -> Path:
        """Where this applier writes, for a dry run that wants to say so."""
        return self._directory

    def apply(self, rendered: dict[str, str], *, autostart_names: list[str]) -> str:
        """Write the rendered files, drop stale ones, and recreate what changed.

        Only containers whose file actually changed are touched: a Quadlet
        start is always a fresh container, so restarting an untouched one
        would throw away its runtime state for nothing. A changed one is
        recreated on its new settings — which is how an edited port or
        variable takes effect, and why anything meant to survive must live in
        a volume. Only files carrying the generated marker are ever removed:
        a Quadlet file a person wrote by hand beside these is theirs.

        Args:
            rendered: File contents keyed by file name.
            autostart_names: Containers that should be running; a changed one
                of these is restarted even if it was stopped. A changed
                container outside the list is restarted only if it is running
                now, and a new one waits for its first Start.

        Returns:
            A short summary of what changed.

        Raises:
            CommandError: If systemd refuses a unit.
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        changed = []
        for file_name, text in rendered.items():
            path = self._directory / file_name
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
                changed.append(file_name)
        for path in self._directory.glob(f"*{self._suffix}"):
            if path.name in rendered:
                continue
            try:
                is_ours = path.read_text(encoding="utf-8").startswith(GENERATED_MARKER)
            except OSError:
                continue
            if is_ours:
                # The unit must stop before its file goes, or systemd keeps
                # running a container nothing declares any more.
                unit = f"{path.stem}.service"
                run(["systemctl", "disable", "--now", unit], is_checked=False)
                path.unlink()
                changed.append(f"-{path.name}")

        run(["systemctl", "daemon-reload"])
        for file_name in rendered:
            if file_name not in changed:
                continue
            name = file_name.removesuffix(self._suffix)
            unit = f"{name}.service"
            if name in autostart_names:
                run(["systemctl", "restart", unit])
                continue
            is_active = run(
                ["systemctl", "is-active", unit], is_checked=False
            ).stdout.strip()
            if is_active == "active":
                run(["systemctl", "restart", unit])
        if not changed:
            return "containers unchanged"
        return f"containers: {', '.join(sorted(changed))}"


class PodmanRegistriesApplier:
    """Installs the docker.io mirror drop-in, or removes it."""

    def apply(self, rendered: str) -> str:
        """Write the drop-in, or take it away when no mirrors are declared.

        Takes effect on the next pull; nothing needs restarting.

        Args:
            rendered: The drop-in text, empty for none.

        Returns:
            A short summary of what changed.
        """
        path = PODMAN_REGISTRIES_CONF_PATH
        if rendered == "":
            if path.is_file():
                path.unlink()
                return "mirrors removed"
            return "no mirrors"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") == rendered:
            return "mirrors unchanged"
        path.write_text(rendered, encoding="utf-8")
        return "mirrors updated"


class PodmanStatusReader:
    """Reads what podman is running right now."""

    def survey(self, *, declared_names: list[str]) -> list[PodmanContainerState]:
        """List every container, running or not.

        Args:
            declared_names: The names config/ declares, to mark ownership.

        Returns:
            One entry per container podman knows, declared ones first. Empty
            when podman is not installed or has nothing.
        """
        result = run(["podman", "ps", "-a", "--format", "json"], is_checked=False)
        if not result.is_success:
            return []
        try:
            entries = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        states = []
        for entry in entries:
            names = entry.get("Names") or ["?"]
            states.append(
                PodmanContainerState(
                    name=names[0],
                    image=entry.get("Image", ""),
                    status=entry.get("Status", ""),
                    is_running=entry.get("State", "") == "running",
                    is_declared=names[0] in declared_names,
                )
            )
        # A declared container with autostart off exists only as a unit until
        # its first start, so podman has no row for it. It still belongs on
        # the list — otherwise it is invisible, and nothing could start it.
        present = {state.name for state in states}
        for name in declared_names:
            if name not in present:
                states.append(
                    PodmanContainerState(
                        name=name,
                        image="",
                        status="not created yet",
                        is_running=False,
                        is_declared=True,
                    )
                )
        states.sort(key=lambda state: (not state.is_declared, state.name))
        return states


class PodmanContainerController:
    """Starts and stops containers, each through its rightful owner."""

    def control(self, name: str, action: str, *, is_declared: bool) -> None:
        """Start, stop or restart one container.

        A declared container is driven through systemd, which supervises it;
        driving it through podman would leave systemd convinced it crashed.
        An ad-hoc container has no unit, so podman is the only handle.

        Args:
            name: The container's name.
            action: One of :data:`CONTAINER_ACTIONS`.
            is_declared: Whether config/ declares it.

        Raises:
            ValueError: For an action outside the list.
            CommandError: If the container refuses.
        """
        if action not in CONTAINER_ACTIONS:
            raise ValueError(
                f"unsupported action {action!r}; "
                f"expected one of {', '.join(CONTAINER_ACTIONS)}"
            )
        if not is_declared:
            run(["podman", action, name], timeout_s=120)
            return
        try:
            run(["systemctl", action, f"{name}.service"])
        except CommandError:
            # netavark's first veth of a boot sometimes fails EINVAL and the
            # unit's own Restart heals it a second later. An error the box
            # already fixed is not one worth showing.
            time.sleep(2)
            is_active = run(
                ["systemctl", "is-active", f"{name}.service"], is_checked=False
            ).stdout.strip()
            if is_active != "active" or action == "stop":
                raise


def hub_tags_url(image: str) -> str | None:
    """The Docker Hub API endpoint listing an image's tags.

    Args:
        image: An image reference, with or without the ``docker.io/`` prefix
            and with or without a tag.

    Returns:
        The URL, or None for an image not hosted on Docker Hub — other
        registries have other APIs, and guessing would 404 confusingly.
    """
    base = image.strip()
    if base.startswith("docker.io/"):
        base = base[len("docker.io/") :]
    elif "." in base.split("/", 1)[0]:
        # Some other registry (ghcr.io/..., quay.io/...).
        return None
    # Drop a tag if one is present: the colon after the last slash.
    colon = base.rfind(":")
    if colon > base.rfind("/"):
        base = base[:colon]
    if "/" not in base:
        base = f"library/{base}"
    if (
        base.count("/") != 1
        or not base.replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(".", "")
        .isalnum()
    ):
        return None
    return (
        f"https://hub.docker.com/v2/repositories/{base}/tags"
        f"?page_size=25&ordering=last_updated"
    )


def list_image_tags(image: str) -> list[str]:
    """Fetch an image's recent tags from Docker Hub.

    Best effort: an unreachable registry or a foreign one yields an empty
    list, and the person types the tag by hand as before.

    Args:
        image: An image reference.

    Returns:
        Tag names, newest first, possibly empty.
    """
    url = hub_tags_url(image)
    if url is None:
        return []
    result = run(["curl", "-fsSL", "--max-time", "10", url], is_checked=False)
    if not result.is_success:
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return [
        entry["name"]
        for entry in payload.get("results", [])
        if isinstance(entry, dict) and entry.get("name")
    ]


def shell_command(name: str) -> list[str]:
    """The command a container shell runs on its pty.

    Args:
        name: A container name that already passed the config pattern or came
            from podman's own listing.

    Returns:
        An argument vector: bash where the image has it, sh where it does not.
    """
    return [
        "podman",
        "exec",
        "-it",
        name,
        "/bin/sh",
        "-c",
        "command -v bash >/dev/null && exec bash || exec sh",
    ]


def is_quadlet_supported() -> bool:
    """Whether the installed podman turns a ``.container`` file into a unit.

    Returns:
        True from podman 4.4. False below it, and False when podman cannot be
        run at all, which is the safe answer: a plain unit works on every
        version, and a Quadlet file on an old podman is inert.
    """
    result = run([PODMAN_BINARY, "--version"], is_checked=False)
    if not result.is_success:
        return False
    words = result.stdout.split()
    return is_version_at_least(words[-1] if words else "", PODMAN_MINIMUM_VERSION)


def container_renderer(config: PodmanConfig):
    """The renderer whose output this machine's podman understands.

    Args:
        config: The declared containers.

    Returns:
        A Quadlet renderer, or a unit renderer on a podman without Quadlet.
    """
    if is_quadlet_supported():
        return PodmanQuadletRenderer(config=config)
    return PodmanUnitRenderer(config=config)


def container_applier() -> PodmanUnitApplier:
    """The applier for whichever files :func:`container_renderer` produced.

    Returns:
        An applier pointed at the directory that machine's podman reads.
    """
    if is_quadlet_supported():
        return PodmanUnitApplier(directory=PODMAN_QUADLET_DIR, suffix=".container")
    return PodmanUnitApplier(directory=PODMAN_UNIT_DIR, suffix=".service")
