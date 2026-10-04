"""What setup writes into config/xray/ from the proxy screen's answers.

The wizard returns answers and is checked on those, the renderers are checked
on the files, and this is the step that turns one into the other.
"""

import pytest

from neutrino_hub.cli import wizard
from neutrino_hub.modules.xray import setup_part
from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR
from tests.conftest import unlock_vault

# A share link the parser accepts, made up: example.com, and the password
# inside the base64 is the words "s3cret-password".
SHARE_LINK = (
    "ss://YWVzLTI1Ni1nY206czNjcmV0LXBhc3N3b3Jk@hk.example.com:5800#HK"  # scan: allow
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` seeded from the examples, as `_step_config_files` leaves it."""
    for name in ("xray/nodes.json", "xray/routing.json"):
        source = UTILS_EXAMPLES_DIR / name.replace(".json", ".example.json")
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def test_the_nodes_replace_the_examples_and_keep_their_settings(config_dir):
    """Building a fresh list dropped the measurement settings the example
    states, and the wizard has no screen that asks for them."""
    from neutrino_hub.utils.json_file import read_config

    setup_part.write_answers(
        wizard.WizardProxy(is_enabled=True, nodes=(parse_share_link(SHARE_LINK),))
    )

    nodes = read_config("xray/nodes.json")
    # The id carries a digest of the address and port, so two servers a
    # provider hands out under one first label stay two nodes.
    assert [node["id"].split("_")[0] for node in nodes["nodes"]] == ["hk"]
    assert nodes["balancer"]["probe_url"], "the example's probe address survived"
    assert nodes["balancer"][
        "reference_url"
    ], "the example's reference address survived"
    # The link's password lands sealed in the vault, never in the file.
    stored = nodes["nodes"][0]
    assert stored["secret_id"]
    assert "password" not in stored["shadowsocks"]
    from neutrino_hub.modules.credentials.vault import SecretVault

    assert SecretVault().open(stored["secret_id"]) == {"value": "s3cret-password"}


def test_every_proxy_answer_reaches_the_routing_file(config_dir):
    from neutrino_hub.utils.json_file import read_config

    setup_part.write_answers(
        wizard.WizardProxy(
            is_enabled=True,
            nodes=(parse_share_link(SHARE_LINK),),
            is_local=True,
            is_socks_proxy_enabled=True,
            socks_proxy_port=1081,
            is_socks_direct_enabled=True,
            socks_direct_port=1088,
        )
    )

    routing = read_config("xray/routing.json")
    assert routing["is_proxy_enabled"] is True
    assert routing["is_local_proxy_enabled"] is True
    # Two questions, one list: each answered port becomes a listener, and
    # which way its traffic leaves is what it carries.
    assert routing["socks_ports"] == [
        {"port": 1081, "is_proxied": True},
        {"port": 1088, "is_proxied": False},
    ]


def _proxy_answered(path: str, is_local: bool, monkeypatch) -> wizard.WizardProxy:
    """The proxy answers of a server, typed in the terminal or sent by the
    browser."""
    if path == "browser":
        document = {
            "password": "a-long-enough-password",
            "vault_passphrase": "A-vault-passphrase-16!",  # scan: allow
            "network": {"mode": "server"},
            "proxy": {"links": [SHARE_LINK], "is_local": is_local},
        }
        return wizard.from_document(document).proxy
    asked = wizard.SetupWizard(links=[])
    asked._mode = "server"
    typed = iter(["2", SHARE_LINK, "", "", "y" if is_local else "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
    assert asked._ask_proxy() == wizard.WIZARD_NEXT
    return asked._proxy


@pytest.mark.parametrize("system", ["darwin", "win32"])
@pytest.mark.parametrize("path", ["terminal", "browser"])
@pytest.mark.parametrize("is_local", [True, False])
def test_macos_and_windows_move_the_overlay_with_this_boxs_own_traffic(
    config_dir, monkeypatch, system, path, is_local
):
    """Both scopes divert the whole machine there, so one answer sets both."""
    from neutrino_hub.utils.json_file import read_config

    monkeypatch.setattr("sys.platform", system)
    setup_part.write_answers(_proxy_answered(path, is_local, monkeypatch))

    routing = read_config("xray/routing.json")
    assert routing["is_local_proxy_enabled"] is is_local
    assert routing["is_overlay_proxy_enabled"] is is_local


@pytest.mark.parametrize("path", ["terminal", "browser"])
def test_linux_leaves_the_overlay_to_the_proxy_page(config_dir, monkeypatch, path):
    from neutrino_hub.utils.json_file import read_config

    monkeypatch.setattr("sys.platform", "linux")
    setup_part.write_answers(_proxy_answered(path, True, monkeypatch))

    routing = read_config("xray/routing.json")
    assert routing["is_local_proxy_enabled"] is True
    assert routing["is_overlay_proxy_enabled"] is False


def test_skipping_the_proxy_empties_the_example_nodes(config_dir):
    """The example ships two nodes with placeholder keys, which xray refuses."""
    from neutrino_hub.utils.json_file import read_config

    setup_part.write_answers(wizard.WizardProxy())

    assert read_config("xray/nodes.json")["nodes"] == []
    assert read_config("xray/routing.json")["is_proxy_enabled"] is False


def test_the_proxy_steps_come_after_the_python_environment():
    """Setup's table takes them from the edition table, in that place."""
    from neutrino_hub.cli import setup

    names = [step_id for step_id, _, _ in setup.CORE_STEPS]

    assert names.index("xray_core") == names.index("python_env") + 1
    assert setup_part.SETUP_STEPS[0][2] is setup_part.step_xray_core


def test_the_service_user_owns_the_log_directory(monkeypatch, tmp_path):
    """On Linux the proxy core's account is made once, and the log directory
    and every xray log in it are handed to it."""
    calls = []

    class Result:
        is_success = False

    def run(command, **keywords):
        calls.append(command[0])
        return Result()

    owned = []
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(setup_part, "run", run)
    monkeypatch.setattr(setup_part, "UTILS_GEODATA_DIR", tmp_path / "geodata")
    monkeypatch.setattr(setup_part, "UTILS_LOG_DIR", tmp_path / "log")
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "xray_error.log").write_text("")
    monkeypatch.setattr(
        setup_part.shutil, "chown", lambda path, user: owned.append((path, user))
    )

    assert setup_part.ensure_service_user() is True
    assert calls == ["id", "useradd"]
    assert (tmp_path / "geodata").is_dir()
    assert [user for _, user in owned] == ["xray", "xray"]
