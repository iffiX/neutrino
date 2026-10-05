"""The rendered app.ini, checked for the choices that keep the box usable."""

from neutrino_agent.modules.gitea.config import GiteaConfig
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer, GiteaLayout

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


def test_the_linux_layout_names_the_git_account_the_work_root_and_ssh():
    rendered = render()

    assert "RUN_USER = git\n" in rendered
    assert "WORK_PATH = /var/lib/gitea\n" in rendered
    assert "DISABLE_SSH = false\n" in rendered
    assert "[git]" not in rendered
    assert "[windows]" not in rendered


def test_a_windows_layout_names_localsystem_its_paths_its_git_and_its_service():
    config = GiteaConfig.from_dict({"secrets": SECRETS, "address": "192.168.100.7"})
    layout = GiteaLayout(
        run_user="NMXWIN$",
        work_path="C:/ProgramData/Neutrino/agent/state/gitea_data",
        git_path="C:/Program Files/Git/cmd/git.exe",
        is_ssh_served=False,
        windows_service_name="neutrino_gitea",
    )

    rendered = GiteaConfigRenderer(config=config, layout=layout).render()

    data = "C:/ProgramData/Neutrino/agent/state/gitea_data"
    assert "RUN_USER = NMXWIN$\n" in rendered
    assert f"WORK_PATH = {data}\n" in rendered
    assert f"PATH = {data}/data/gitea.db\n" in rendered
    assert f"ROOT_PATH = {data}/log\n" in rendered
    assert "DISABLE_SSH = true\n" in rendered
    assert rendered.endswith(
        "\n[git]\nPATH = C:/Program Files/Git/cmd/git.exe\n"
        "\n[windows]\nSERVICE_NAME = neutrino_gitea\n"
    )
