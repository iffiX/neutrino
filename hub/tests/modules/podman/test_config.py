"""The container declarations and the checks that keep systemd able to run
them — or a flag out of a command line."""

import pytest

from neutrino_hub.modules.podman.config import PodmanConfig


def config_with(**overrides) -> PodmanConfig:
    data = {
        "containers": [
            {"name": "redis", "image": "docker.io/library/redis:7"},
        ]
    }
    data.update(overrides)
    return PodmanConfig.from_dict(data)


def test_a_sound_configuration_passes():
    config_with().validate()


def test_the_parse_survives_a_round_trip():
    config = config_with()

    assert PodmanConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


@pytest.mark.parametrize("name", ["", "Redis", "a b", "-x", "x\ny", "x" * 65])
def test_a_name_that_is_not_a_unit_name_is_refused(name):
    config = config_with(containers=[{"name": name, "image": "img"}])

    with pytest.raises(ValueError):
        config.validate()


def test_two_containers_cannot_share_a_name():
    config = config_with(
        containers=[
            {"name": "redis", "image": "a"},
            {"name": "redis", "image": "b"},
        ]
    )

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("image", ["", "bad image", "a\nb"])
def test_an_image_with_whitespace_is_refused(image):
    config = config_with(containers=[{"name": "x", "image": image}])

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("port", ["80", "80:80:80", "eighty:80", "80:80/icmp"])
def test_a_port_that_is_not_a_mapping_is_refused(port):
    config = config_with(containers=[{"name": "x", "image": "img", "ports": [port]}])

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("port", ["8080:80", "53:53/udp", "443:8443/tcp"])
def test_a_sound_port_mapping_passes(port):
    config_with(containers=[{"name": "x", "image": "img", "ports": [port]}]).validate()


@pytest.mark.parametrize(
    "volume",
    ["novolume", "relative/path:/data", "/host:relative", "a:b\n:/x"],
)
def test_a_volume_that_is_not_source_destination_is_refused(volume):
    config = config_with(
        containers=[{"name": "x", "image": "img", "volumes": [volume]}]
    )

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("volume", ["/srv/share:/data", "cache:/var/cache"])
def test_a_sound_volume_passes(volume):
    config_with(
        containers=[{"name": "x", "image": "img", "volumes": [volume]}]
    ).validate()


@pytest.mark.parametrize("entry", ["NOEQUALS", "1BAD=x", "K=v\nInjected=y"])
def test_an_environment_line_that_is_not_key_value_is_refused(entry):
    config = config_with(
        containers=[{"name": "x", "image": "img", "environment": [entry]}]
    )

    with pytest.raises(ValueError):
        config.validate()


def test_hub_urls_resolve_and_foreign_registries_decline():
    """Tag listing is a Docker Hub convenience, never a guess at another
    registry's API."""
    from neutrino_hub.modules.podman.ops import hub_tags_url

    assert "repositories/library/python/tags" in hub_tags_url("python")
    assert "repositories/library/redis/tags" in hub_tags_url(
        "docker.io/library/redis:7"
    )
    assert "repositories/ann/tool/tags" in hub_tags_url("docker.io/ann/tool")
    assert hub_tags_url("ghcr.io/owner/thing") is None
    assert hub_tags_url("quay.io/owner/thing:1") is None


@pytest.mark.parametrize("mirror", ["https://mirror.example.com", "bad mirror", "a\nb"])
def test_a_mirror_that_is_a_url_or_garbled_is_refused(mirror):
    config = config_with(mirrors=[mirror])

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize(
    "mirror", ["mirror.ccs.tencentyun.com", "registry.local:5000", "host/path"]
)
def test_a_sound_mirror_passes(mirror):
    config_with(mirrors=[mirror]).validate()
