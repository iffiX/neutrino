"""The rendered app.ini, checked for the choices that keep the box usable."""

from neutrino_agent.modules.gitea.config import GiteaConfig
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer

SECRETS = {
    "SECRET_KEY": "sk",
    "INTERNAL_TOKEN": "it",
    "JWT_SECRET": "jw",
    "LFS_JWT_SECRET": "lf",
}


def render(**fields) -> str:
    config = GiteaConfig.from_dict(
        {"secrets": SECRETS, "address": "192.168.100.7", **fields}
    )
    config.validate()
    return GiteaConfigRenderer(config=config).render()


def test_the_install_wizard_is_locked_out():
    assert "INSTALL_LOCK = true" in render()


def test_the_root_url_derives_from_the_address_when_unset():
    rendered = render(listen_port=3100)

    assert "ROOT_URL = http://192.168.100.7:3100/" in rendered
    assert "DOMAIN = 192.168.100.7" in rendered
    assert "HTTP_PORT = 3100" in rendered


def test_a_root_url_override_carries_its_own_domain():
    rendered = render(root_url="http://gateway.tail:3000/")

    assert "ROOT_URL = http://gateway.tail:3000/" in rendered
    assert "DOMAIN = gateway.tail" in rendered
    assert "SSH_DOMAIN = gateway.tail" in rendered


def test_registration_follows_the_switch():
    assert "DISABLE_REGISTRATION = true" in render()
    assert "DISABLE_REGISTRATION = false" in render(is_registration_enabled=True)


def test_every_secret_lands():
    rendered = render()

    for value in SECRETS.values():
        assert f"= {value}" in rendered


def test_the_ui_never_reaches_for_a_cdn():
    assert "OFFLINE_MODE = true" in render()
