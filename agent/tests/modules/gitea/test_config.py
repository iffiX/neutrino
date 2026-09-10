"""The git server's configuration and the checks that keep it servable."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.gitea.config import GiteaConfig

SECRETS = {
    "SECRET_KEY": "sk",
    "INTERNAL_TOKEN": "it",
    "JWT_SECRET": "jw",
    "LFS_JWT_SECRET": "lf",
}


def config(**fields) -> GiteaConfig:
    return GiteaConfig.from_dict(
        {"secrets": SECRETS, "address": "192.168.100.7", **fields}
    )


def test_a_sound_configuration_passes():
    config(listen_port=3000).validate()


def test_the_parse_survives_a_round_trip():
    held = config(listen_port=3100, root_url="http://box:3100/")

    assert GiteaConfig.from_dict(held.to_dict()).to_dict() == held.to_dict()


def test_the_root_url_derives_from_the_address_when_unset():
    assert config(listen_port=3100).derived_root_url == "http://192.168.100.7:3100/"
    assert config(root_url="http://box/").derived_root_url == "http://box/"


@pytest.mark.parametrize("port", [0, -1, 70000, "nonsense"])
def test_a_non_port_is_refused(port):
    with pytest.raises(ModuleApplyError) as refused:
        config(listen_port=port).validate()

    assert refused.value.code == "port_invalid"


@pytest.mark.parametrize("port", [53, 80, 1080])
def test_a_port_the_hub_already_owns_is_refused(port):
    with pytest.raises(ModuleApplyError) as refused:
        config(listen_port=port).validate()

    assert refused.value.code == "port_reserved"


@pytest.mark.parametrize("url", ["box:3000", "ftp://box/", "http://a\nb/"])
def test_a_root_url_that_is_not_a_web_url_is_refused(url):
    with pytest.raises(ModuleApplyError) as refused:
        config(root_url=url).validate()

    assert refused.value.code == "root_url_invalid"


def test_missing_secrets_are_refused_by_name():
    with pytest.raises(ModuleApplyError) as refused:
        config(secrets={"SECRET_KEY": "sk"}).validate()

    assert refused.value.code == "secrets_missing"
    assert refused.value.params["names"] == [
        "INTERNAL_TOKEN",
        "JWT_SECRET",
        "LFS_JWT_SECRET",
    ]
