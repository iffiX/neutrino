"""The rendered container files, checked for what systemd will read."""

from neutrino_agent.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_agent.modules.podman.constants import PODMAN_GENERATED_MARKER
from neutrino_agent.modules.podman.renderer import (
    PodmanQuadletRenderer,
    PodmanRegistriesRenderer,
    PodmanUnitRenderer,
    qualified_image,
)


def render(containers: list) -> dict:
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
    assert set(render([FULL, {"name": "redis", "image": "r"}])) == {
        "webdav.container",
        "redis.container",
    }


def test_every_declared_knob_lands_in_the_unit():
    text = render([FULL])["webdav.container"]

    assert "ContainerName=webdav" in text
    assert "Image=docker.io/library/nginx:1" in text
    assert "PublishPort=8081:80" in text
    assert "Volume=/srv/share:/usr/share/nginx/html" in text
    assert "Environment=TZ=Asia/Shanghai" in text
    assert "WantedBy=multi-user.target" in text
    assert "TimeoutStartSec=900" in text


def test_no_autostart_means_no_install_section():
    text = render([{**FULL, "is_autostart": False}])["webdav.container"]

    assert "[Install]" not in text


def test_every_file_carries_the_marker_that_makes_removal_safe():
    for text in render([FULL, {"name": "redis", "image": "r"}]).values():
        assert text.startswith(PODMAN_GENERATED_MARKER)


def test_short_image_names_are_qualified_in_the_unit():
    assert qualified_image("python:3.12") == "docker.io/library/python:3.12"
    assert qualified_image("iffi/tool:1") == "docker.io/iffi/tool:1"
    assert qualified_image("ghcr.io/owner/thing:2") == "ghcr.io/owner/thing:2"
    assert qualified_image("localhost:5000/x") == "localhost:5000/x"


def test_mirrors_render_in_order_and_none_renders_nothing():
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
    assert PodmanRegistriesRenderer(config=PodmanConfig()).render() == ""


def test_a_command_overrides_the_images_own_and_absent_stays_absent():
    with_command = render(
        [{"name": "py", "image": "python:3.12", "command": "python3 -m http.server"}]
    )["py.container"]
    without = render([{"name": "py", "image": "python:3.12"}])["py.container"]

    assert "Exec=python3 -m http.server" in with_command
    assert "Exec=" not in without


def unit(container: PodmanContainer) -> str:
    config = PodmanConfig(containers=[container], mirrors=[])
    return PodmanUnitRenderer(config=config).render()[f"{container.name}.service"]


def exec_start(container: PodmanContainer) -> str:
    for line in unit(container).splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("the unit has no ExecStart")


def test_a_unit_is_named_the_same_as_its_quadlet_file_would_be():
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
    line = exec_start(
        PodmanContainer(
            name="app", image="nginx", environment=["JAVA_OPTS=-Xmx1g -Xms512m"]
        )
    )
    assert '-e "JAVA_OPTS=-Xmx1g -Xms512m"' in line


def test_a_command_is_passed_through_for_systemd_to_split():
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
    assert unit(PodmanContainer(name="app", image="nginx")).startswith(
        PODMAN_GENERATED_MARKER
    )
