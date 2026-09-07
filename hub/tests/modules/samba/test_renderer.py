"""The rendered smb.conf, checked line by line and by Samba itself.

The renderer owns the whole file, so what matters is as much what is absent —
printers, guests, the stock password-sync glue — as what is present.
"""

import shutil
import subprocess

import pytest

from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.renderer import SambaConfigRenderer, share_subnets

from tests.conftest import lan_entry, network_config, wan_entry, without_comments

LAN = ["192.168.100.0/24"]


def render(config_data: dict, lan_subnets=None) -> str:
    config = SambaConfig.from_dict(config_data)
    config.validate()
    return SambaConfigRenderer(
        config=config, lan_subnets=LAN if lan_subnets is None else lan_subnets
    ).render()


def validate_smb_conf(rendered: str, tmp_path) -> None:
    """Run the real ``testparm`` over a rendered file."""
    if shutil.which("testparm") is None:
        pytest.skip("samba is not installed here")
    path = tmp_path / "smb.conf"
    path.write_text(rendered, encoding="utf-8")
    result = subprocess.run(
        ["testparm", "-s", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"testparm rejected the render: {result.stderr}"


BASIC = {
    "shares": [
        {"name": "share", "path": "/srv/share", "comment": "Shared space"},
    ],
    "users": ["ann", "bob"],
}


def test_samba_itself_accepts_the_render(tmp_path):
    validate_smb_conf(render(BASIC), tmp_path)


def test_the_lan_is_the_only_place_a_share_answers():
    rendered = without_comments(render(BASIC))

    assert "hosts allow = 192.168.100.0/24 127.0.0.1" in rendered
    assert "hosts deny = 0.0.0.0/0" in rendered


def test_nothing_of_the_stock_configuration_survives():
    """The stock file exports printers and syncs passwords with PAM; a
    rendered file that let either back in would be quietly serving them."""
    rendered = without_comments(render(BASIC)).lower()

    assert "printers" not in rendered.replace("load printers", "")
    assert "load printers = no" in rendered
    assert "guest" not in rendered.replace("map to guest = never", "")
    assert "unix password sync" not in rendered


def test_an_open_share_admits_the_group_a_restricted_one_its_names():
    data = {
        "shares": [
            {"name": "open", "path": "/srv/open"},
            {"name": "mine", "path": "/srv/mine", "valid_users": ["ann"]},
        ],
        "users": ["ann", "bob"],
    }

    rendered = without_comments(render(data))

    open_block = rendered.split("[open]")[1].split("[mine]")[0]
    mine_block = rendered.split("[mine]")[1]
    assert "valid users = @sambashare" in open_block
    assert "valid users = ann" in mine_block


def test_a_read_only_share_does_not_arrange_for_writing():
    """force group and the masks exist so writers can share files; on a share
    that refuses writing they would only be noise claiming otherwise."""
    data = {
        "shares": [{"name": "archive", "path": "/srv/a", "is_read_only": True}],
        "users": [],
    }

    rendered = without_comments(render(data))

    assert "read only = yes" in rendered
    assert "force group" not in rendered
    assert "create mask" not in rendered


def test_two_lans_are_both_allowed():
    rendered = without_comments(
        render(BASIC, lan_subnets=["192.168.100.0/24", "192.168.101.0/24"])
    )

    assert "hosts allow = 192.168.100.0/24 192.168.101.0/24 127.0.0.1" in rendered


def test_no_shares_still_renders_a_servable_file(tmp_path):
    rendered = render({"shares": [], "users": ["ann"]})

    validate_smb_conf(rendered, tmp_path)
    assert "[global]" in rendered


def test_allowed_subnets_carries_exposed_networks_where_no_lan_has_a_role():
    """A server-mode box has no LAN-role interface, and its shares answer
    the networks the owner exposed — loopback-only was nobody's intent."""
    from neutrino_hub.modules.samba.renderer import allowed_subnets

    assert allowed_subnets([], ["192.168.100.1/24"]) == ["192.168.100.0/24"]
    assert allowed_subnets(
        ["192.168.93.1/24"], ["192.168.100.1/24", "192.168.93.1/24", "", "bad"]
    ) == ["192.168.93.0/24", "192.168.100.0/24"]
    assert allowed_subnets([], [None, ""]) == []


def test_a_router_renders_its_shares_without_asking_a_property_to_run():
    """The two call sites both read the exposed set, and both called it. A
    router-mode box could not render smb.conf at all."""
    network = network_config(
        wan_entry("enp2s0"),
        lan_entry("enp1s0", address="192.168.100.1", is_exposed=True),
    )

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24", "enp2s0": "10.0.0.5/24"},
        device_addresses={},
    )

    assert subnets == ["192.168.100.0/24"]


def test_an_exposed_overlay_is_allowed_where_the_firewall_already_lets_it_in():
    """The firewall opening a network the shares then refuse is two fences
    disagreeing, and the person sees a share that will not mount."""
    network = network_config(lan_entry("enp1s0", address="192.168.100.1"))

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24"},
        device_addresses={"wt0": "100.88.178.129/16"},
    )

    assert subnets == ["192.168.100.0/24", "100.88.0.0/16"]


def test_a_closed_overlay_stays_out_of_the_share_fence():
    network = network_config(
        lan_entry("enp1s0", address="192.168.100.1"),
        overlays=[{"provider": "netbird", "is_exposed": False}],
    )

    subnets = share_subnets(
        network=network,
        link_addresses={"enp1s0": "192.168.100.1/24"},
        device_addresses={"wt0": "100.88.178.129/16"},
    )

    assert subnets == ["192.168.100.0/24"]
