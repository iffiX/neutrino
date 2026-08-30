"""The rendered app.ini, checked for the choices that keep the box usable."""

from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.renderer import GiteaConfigRenderer

SECRETS = {
    "SECRET_KEY": "sk",
    "INTERNAL_TOKEN": "it",
    "JWT_SECRET": "jw",
    "LFS_JWT_SECRET": "lf",
}


def render(config_data: dict) -> str:
    config = GiteaConfig.from_dict(config_data)
    config.validate()
    return GiteaConfigRenderer(
        config=config, lan_address="192.168.100.1", secrets=SECRETS
    ).render()


def test_the_install_wizard_is_locked_out():
    """A box that boots into 'please configure me' is not plug-and-play."""
    assert "INSTALL_LOCK = true" in render({})


def test_the_root_url_derives_from_the_lan_when_unset():
    rendered = render({"listen_port": 3100})

    assert "ROOT_URL = http://192.168.100.1:3100/" in rendered
    assert "DOMAIN = 192.168.100.1" in rendered


def test_a_root_url_override_carries_its_own_domain():
    rendered = render({"root_url": "http://gateway.tail:3000/"})

    assert "ROOT_URL = http://gateway.tail:3000/" in rendered
    assert "DOMAIN = gateway.tail" in rendered
    assert "SSH_DOMAIN = gateway.tail" in rendered


def test_registration_follows_the_switch():
    assert "DISABLE_REGISTRATION = true" in render({})
    assert "DISABLE_REGISTRATION = false" in render({"is_registration_enabled": True})


def test_every_secret_lands_and_none_is_a_placeholder():
    rendered = render({})

    for value in SECRETS.values():
        assert f"= {value}" in rendered


def test_the_ui_never_reaches_for_a_cdn():
    """Half the UI hanging on a blocked CDN would look like a broken Gitea."""
    assert "OFFLINE_MODE = true" in render({})
