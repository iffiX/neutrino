"""The rendered container files, checked for what systemd will read.

A machine with Quadlet gets `.container` files and one without gets `.service`
files that say the same thing; both are checked here against the same
configuration.
"""

from neutrino_hub.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_hub.modules.podman.constants import PODMAN_QUADLET_DIR, PODMAN_UNIT_DIR
from neutrino_hub.modules.podman.renderer import (
    GENERATED_MARKER,
    PodmanQuadletRenderer,
    PodmanRegistriesRenderer,
    PodmanUnitRenderer,
)


def render(containers: list[dict]) -> dict[str, str]:
    config = PodmanConfig.from_dict({"containers": containers})
    config.validate()
    return PodmanQuadletRenderer(config=config).render()


FULL = {
    "name": "webdav",
    "image": "docker.io/library/nginx:1",
    "ports": ["8081:80"],
    "volumes": ["/srv/share:/usr/share/nginx/html"],
    "environment": ["TZ=Asia/Shanghai"],
    "is_autostart": True,
}


def test_one_file_per_container_named_for_it():
    rendered = render([FULL, {"name": "redis", "image": "r"}])

    assert set(rendered) == {"webdav.container", "redis.container"}


def test_every_declared_knob_lands_in_the_unit():
    text = render([FULL])["webdav.container"]

    assert "ContainerName=webdav" in text
    assert "Image=docker.io/library/nginx:1" in text
    assert "PublishPort=8081:80" in text
    assert "Volume=/srv/share:/usr/share/nginx/html" in text
    assert "Environment=TZ=Asia/Shanghai" in text
    assert "WantedBy=multi-user.target" in text


def test_no_autostart_means_no_install_section():
    """Without [Install] the unit exists but nothing pulls it up at boot."""
    text = render([{**FULL, "is_autostart": False}])["webdav.container"]

    assert "[Install]" not in text
    assert "WantedBy" not in text


def test_every_file_carries_the_marker_that_makes_removal_safe():
    """Apply deletes stale files only when they carry this first line; a file
    a person wrote by hand must never qualify."""
    for text in render([FULL, {"name": "redis", "image": "r"}]).values():
        assert text.startswith(GENERATED_MARKER)


def test_first_start_is_given_time_to_pull():
    text = render([FULL])["webdav.container"]

    assert "TimeoutStartSec=900" in text


def test_short_image_names_are_qualified_in_the_unit():
    """The page keeps `python:3.12`; the unit must spell out the registry, or
    boot-time pulls stop to ask which one was meant."""
    from neutrino_hub.modules.podman.renderer import qualified_image

    assert qualified_image("python:3.12") == "docker.io/library/python:3.12"
    assert qualified_image("iffi/tool:1") == "docker.io/iffi/tool:1"
    assert qualified_image("ghcr.io/owner/thing:2") == "ghcr.io/owner/thing:2"
    assert qualified_image("localhost:5000/x") == "localhost:5000/x"
    text = render([{"name": "py", "image": "python:3.12"}])["py.container"]
    assert "Image=docker.io/library/python:3.12" in text


def test_mirrors_render_in_order_and_none_renders_nothing():
    """Order matters — pulls try mirrors first-to-last — and an empty list
    must produce no file at all rather than an empty [[registry]] block."""
    from neutrino_hub.modules.podman.config import PodmanConfig
    from neutrino_hub.modules.podman.renderer import PodmanRegistriesRenderer

    config = PodmanConfig.from_dict(
        {
            "containers": [],
            "mirrors": ["mirror.ccs.tencentyun.com", "registry.docker-cn.com"],
        }
    )
    text = PodmanRegistriesRenderer(config=config).render()

    assert 'prefix = "docker.io"' in text
    assert text.index("mirror.ccs.tencentyun.com") < text.index(
        "registry.docker-cn.com"
    )
    empty = PodmanRegistriesRenderer(
        config=PodmanConfig.from_dict({"containers": []})
    ).render()
    assert empty == ""


def test_a_command_overrides_the_images_own_and_absent_stays_absent():
    """A python image's default command is a REPL that exits without a
    terminal; Exec= is how such an image becomes a service."""
    with_command = render(
        [
            {
                "name": "py",
                "image": "python:3.12",
                "command": "python3 -m http.server 8000",
            }
        ]
    )["py.container"]
    without = render([{"name": "py", "image": "python:3.12"}])["py.container"]

    assert "Exec=python3 -m http.server 8000" in with_command
    assert "Exec=" not in without


def unit(container: PodmanContainer) -> str:
    """The pre-Quadlet unit for one container."""
    config = PodmanConfig(containers=[container], mirrors=[])
    return PodmanUnitRenderer(config=config).render()[f"{container.name}.service"]


def exec_start(container: PodmanContainer) -> str:
    for line in unit(container).splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("the unit has no ExecStart")


def test_a_unit_is_named_the_same_as_its_quadlet_file_would_be():
    """Nothing downstream of the render can tell which renderer produced it."""
    container = PodmanContainer(name="redis", image="redis:7")
    config = PodmanConfig(containers=[container], mirrors=[])
    assert set(PodmanUnitRenderer(config=config).render()) == {"redis.service"}
    assert set(PodmanQuadletRenderer(config=config).render()) == {"redis.container"}


def test_the_six_container_properties_reach_the_command_line():
    line = exec_start(
        PodmanContainer(
            name="app",
            image="nginx",
            ports=["8080:80", "5353:53/udp"],
            volumes=["/srv/data:/data", "cache:/cache"],
            environment=["TZ=UTC"],
        )
    )
    assert "--name app" in line
    assert "-p 8080:80" in line and "-p 5353:53/udp" in line
    assert "-v /srv/data:/data" in line and "-v cache:/cache" in line
    assert "-e TZ=UTC" in line
    assert line.endswith("docker.io/library/nginx")


def test_an_environment_value_with_spaces_stays_one_argument():
    """`-e JAVA_OPTS=-Xmx1g -Xms512m` would otherwise reach podman as two."""
    line = exec_start(
        PodmanContainer(
            name="app", image="nginx", environment=["JAVA_OPTS=-Xmx1g -Xms512m"]
        )
    )
    assert '-e "JAVA_OPTS=-Xmx1g -Xms512m"' in line


def test_a_command_is_passed_through_for_systemd_to_split():
    """Quadlet hands Exec= to systemd whole; this has to mean the same thing."""
    line = exec_start(
        PodmanContainer(name="app", image="python:3.12", command='sh -c "sleep 3600"')
    )
    assert line.endswith('docker.io/library/python:3.12 sh -c "sleep 3600"')


def test_a_leftover_container_does_not_block_the_next_start():
    text = unit(PodmanContainer(name="app", image="nginx"))
    assert "ExecStartPre=-/usr/bin/podman rm -f app" in text
    assert "ExecStop=/usr/bin/podman stop -t 10 app" in text


def test_only_an_autostart_container_is_wanted_by_the_boot_target():
    assert "WantedBy=multi-user.target" in unit(
        PodmanContainer(name="app", image="nginx", is_autostart=True)
    )
    assert "WantedBy=" not in unit(
        PodmanContainer(name="app", image="nginx", is_autostart=False)
    )


def test_a_rendered_unit_carries_the_generated_marker():
    """The applier removes only its own files, on both paths."""
    assert unit(PodmanContainer(name="app", image="nginx")).startswith(GENERATED_MARKER)


def test_the_version_line_podman_prints_decides_which_renderer(monkeypatch):
    """`podman --version` says `podman version 3.4.4`; only the last word counts."""
    from neutrino_hub.modules.podman import ops
    from neutrino_hub.utils.subprocess_run import CommandResult

    def reply(text: str, *, is_success: bool = True):
        return lambda command, **kwargs: CommandResult(
            command=command, exit_code=0 if is_success else 1, stdout=text, stderr=""
        )

    monkeypatch.setattr(ops, "run", reply("podman version 3.4.4\n"))
    assert ops.is_quadlet_supported() is False
    assert ops.container_applier().directory == PODMAN_UNIT_DIR

    monkeypatch.setattr(ops, "run", reply("podman version 4.9.4-rhel\n"))
    assert ops.is_quadlet_supported() is True
    assert ops.container_applier().directory == PODMAN_QUADLET_DIR


def test_a_podman_that_will_not_run_gets_the_unit_that_works_everywhere():
    """A Quadlet file on an old podman is inert; a plain unit never is."""
    from neutrino_hub.modules.podman import ops
    from neutrino_hub.utils.subprocess_run import CommandResult

    ops.run = lambda command, **kwargs: CommandResult(
        command=command, exit_code=127, stdout="", stderr="not found"
    )
    try:
        assert ops.is_quadlet_supported() is False
    finally:
        from neutrino_hub.utils.subprocess_run import run as real_run

        ops.run = real_run
