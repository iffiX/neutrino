"""The rendered Quadlet files, checked for what systemd will read."""

from neutrino_hub.modules.podman.config import PodmanConfig
from neutrino_hub.modules.podman.renderer import GENERATED_MARKER, PodmanQuadletRenderer


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
    from neutrino_hub.modules.podman.renderer import PodmanQuadletRenderer

    config = PodmanConfig.from_dict(
        {
            "containers": [],
            "mirrors": ["mirror.ccs.tencentyun.com", "registry.docker-cn.com"],
        }
    )
    text = PodmanQuadletRenderer(config=config).render_registries()

    assert 'prefix = "docker.io"' in text
    assert text.index("mirror.ccs.tencentyun.com") < text.index(
        "registry.docker-cn.com"
    )
    empty = PodmanQuadletRenderer(
        config=PodmanConfig.from_dict({"containers": []})
    ).render_registries()
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
