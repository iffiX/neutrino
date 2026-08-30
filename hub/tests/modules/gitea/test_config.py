"""The git server's configuration and the checks that keep it servable."""

import pytest

from neutrino_hub.modules.gitea.config import GiteaConfig


def test_a_sound_configuration_passes():
    GiteaConfig.from_dict({"listen_port": 3000}).validate()


def test_the_parse_survives_a_round_trip():
    config = GiteaConfig.from_dict(
        {"listen_port": 3100, "root_url": "http://box:3100/"}
    )

    assert GiteaConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_a_non_port_is_refused(port):
    with pytest.raises(ValueError):
        GiteaConfig.from_dict({"listen_port": port}).validate()


@pytest.mark.parametrize("port", [53, 80, 1080])
def test_a_port_the_gateway_already_owns_is_refused(port):
    """Applying one of these would render fine and then fail to bind — or
    worse, race the gateway's own service for its socket."""
    with pytest.raises(ValueError):
        GiteaConfig.from_dict({"listen_port": port}).validate()


@pytest.mark.parametrize("url", ["box:3000", "ftp://box/", "http://a\nb/"])
def test_a_root_url_that_is_not_a_web_url_is_refused(url):
    with pytest.raises(ValueError):
        GiteaConfig.from_dict({"root_url": url}).validate()
