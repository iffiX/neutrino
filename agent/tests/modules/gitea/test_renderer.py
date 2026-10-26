"""The rendered app.ini, checked for the choices that keep the box usable."""

from neutrino_agent.modules.gitea.config import GiteaConfig
from neutrino_agent.modules.gitea.renderer import GiteaConfigRenderer, GiteaLayout

SECRETS = {
    "SECRET_KEY": "sk",
    "INTERNAL_TOKEN": "it",
    "JWT_SECRET": "jw",
    "LFS_JWT_SECRET": "lf",
}


def render(ssh_listen_port=2222, **fields) -> str:
    config = GiteaConfig.from_dict(
        {"secrets": SECRETS, "address": "192.168.100.7", **fields}
    )
    config.validate()
    return GiteaConfigRenderer(config=config, ssh_listen_port=ssh_listen_port).render()


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
    assert "\nDOMAIN = gateway.tail\n" in rendered


def test_registration_follows_the_switch():
    assert "DISABLE_REGISTRATION = true" in render()
    assert "DISABLE_REGISTRATION = false" in render(is_registration_enabled=True)


def test_every_secret_lands():
    rendered = render()

    for value in SECRETS.values():
        assert f"= {value}" in rendered


def test_the_ui_never_reaches_for_a_cdn():
    assert "OFFLINE_MODE = true" in render()


def test_the_linux_layout_names_the_git_account_and_the_work_root():
    rendered = render()

    assert "RUN_USER = git\n" in rendered
    assert "WORK_PATH = /var/lib/gitea\n" in rendered
    assert "[git]" not in rendered
    assert "[windows]" not in rendered


def test_gitea_s_own_ssh_server_listens_on_loopback_and_clones_name_the_forward():
    """git over SSH reaches Gitea through a client's forward of the ssh entry,
    whose local port is the same on every client."""
    rendered = render(ssh_listen_port=2223, ssh_port=27654)

    assert "DISABLE_SSH = false\n" in rendered
    assert "START_SSH_SERVER = true\n" in rendered
    assert "SSH_LISTEN_HOST = 127.0.0.1\n" in rendered
    assert "SSH_LISTEN_PORT = 2223\n" in rendered
    assert "SSH_DOMAIN = 127.0.0.1\n" in rendered
    assert "SSH_PORT = 27654\n" in rendered


def test_with_no_local_port_named_clones_name_the_listen_port():
    assert "SSH_PORT = 2222\n" in render()


def test_a_windows_layout_names_localsystem_its_paths_its_git_and_its_service():
    config = GiteaConfig.from_dict({"secrets": SECRETS, "address": "192.168.100.7"})
    layout = GiteaLayout(
        run_user="NMXWIN$",
        work_path="C:/ProgramData/Neutrino/agent/state/gitea_data",
        git_path="C:/Program Files/Git/cmd/git.exe",
        windows_service_name="neutrino_gitea",
    )

    rendered = GiteaConfigRenderer(
        config=config, layout=layout, ssh_listen_port=2222
    ).render()

    data = "C:/ProgramData/Neutrino/agent/state/gitea_data"
    assert "RUN_USER = NMXWIN$\n" in rendered
    assert f"WORK_PATH = {data}\n" in rendered
    assert f"PATH = {data}/data/gitea.db\n" in rendered
    assert f"ROOT_PATH = {data}/log\n" in rendered
    assert "START_SSH_SERVER = true\n" in rendered
    assert rendered.endswith(
        "\n[git]\nPATH = C:/Program Files/Git/cmd/git.exe\n"
        "\n[windows]\nSERVICE_NAME = neutrino_gitea\n"
    )


def test_the_server_listens_on_loopback_alone_on_every_system():
    """The agent's connect stream dials 127.0.0.1, so no firewall port is
    opened for the server anywhere."""
    config = GiteaConfig.from_dict({"secrets": SECRETS, "address": "192.168.100.7"})
    layouts = (
        GiteaLayout(),
        GiteaLayout(
            run_user="neutrino_gitea",
            work_path="/Library/Application Support/Neutrino/agent/state/gitea_data",
            git_path="/opt/homebrew/bin/git",
        ),
        GiteaLayout(
            run_user="NMXWIN$",
            work_path="C:/ProgramData/Neutrino/agent/state/gitea_data",
            git_path="C:/Program Files/Git/cmd/git.exe",
            windows_service_name="neutrino_gitea",
        ),
    )

    for layout in layouts:
        rendered = GiteaConfigRenderer(config=config, layout=layout).render()
        assert "\nHTTP_ADDR = 127.0.0.1\n" in rendered
        assert "\nSSH_LISTEN_HOST = 127.0.0.1\n" in rendered
        assert "0.0.0.0" not in rendered


def test_links_and_clone_addresses_follow_the_address_the_page_is_opened_at():
    """A client opens Gitea at its own forward, so a link built from ROOT_URL
    would name an address that serves nothing."""
    assert "PUBLIC_URL_DETECTION = auto" in render()
