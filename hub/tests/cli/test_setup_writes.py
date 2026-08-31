"""What `nhub setup` writes into `config/` from what the wizard collected.

This is the layer between the two that neither of them tests: the wizard
returns answers and is checked on those, the renderers are checked on the
files, and the step that turns one into the other was found broken by a VM
install rather than by anything here.
"""

import pytest

from neutrino_hub.cli import setup, wizard
from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR

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
    return tmp_path


def test_the_nodes_replace_the_examples_and_keep_their_settings(config_dir):
    """Building a fresh list dropped the balancer strategy and the probe, and
    the constructor refused it — on a VM, not here."""
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(
        wizard.WizardProxy(is_enabled=True, nodes=(parse_share_link(SHARE_LINK),))
    )

    nodes = read_config("xray/nodes.json")
    assert [node["id"] for node in nodes["nodes"]] == ["hk"]
    assert nodes["balancer"]["strategy"], "the example's strategy survived"


def test_every_proxy_answer_reaches_the_routing_file(config_dir):
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(
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
    assert routing["is_socks_proxy_enabled"] is True
    assert routing["socks_proxy_port"] == 1081
    assert routing["is_socks_direct_enabled"] is True
    assert routing["socks_direct_port"] == 1088


def test_skipping_the_proxy_empties_the_example_nodes(config_dir):
    """The example ships two nodes with placeholder keys, which xray refuses."""
    from neutrino_hub.utils.json_file import read_config

    setup._write_proxy(wizard.WizardProxy())

    assert read_config("xray/nodes.json")["nodes"] == []
    assert read_config("xray/routing.json")["is_proxy_enabled"] is False
