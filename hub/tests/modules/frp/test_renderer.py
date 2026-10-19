"""frpc's file from a vendor's config, and frpc's lines read as states.

The file holds the named fields alone: a vendor's config carrying a
plugin, visitors, a web server, includes or another tunnel's proxy gives a
file without any of them, and the hub sets ``localIP``, ``localPort``,
``loginFailExit`` and ``log.to`` itself.
"""

import tomllib

import pytest

from neutrino_hub.modules.frp.renderer import (
    judge_exit,
    refused_line,
    render_frpc,
    server_port,
)
from tests.modules.frp.fake_vendors import OPENFRP_NODE_CONFIG, SAKURAFRP_CONFIG


def rendered(text=SAKURAFRP_CONFIG, name="neutrino", port=18443) -> dict:
    return tomllib.loads(render_frpc(text, tunnel_name=name, loopback_port=port))


def test_the_file_holds_the_named_fields_and_the_hubs_own():
    assert rendered() == {
        "serverAddr": "frp-a.natfrp.cloud",
        "serverPort": 7001,
        "user": "a1b2c3d4.neutrino",
        "loginFailExit": True,
        "log": {"to": "console"},
        "auth": {"method": "token", "token": "SakuraFrpNodeToken"},
        "metadatas": {"sakura": "neutrino"},
        "transport": {
            "protocol": "tcp",
            "tls": {"enable": True},
            "heartbeatInterval": 30,
        },
        "proxies": [
            {
                "name": "neutrino",
                "type": "tcp",
                "remotePort": 41234,
                "localIP": "127.0.0.1",
                "localPort": 18443,
                "transport": {"useEncryption": True},
                "metadatas": {"tunnel": "114514"},
            }
        ],
    }


@pytest.mark.parametrize("left_out", ["includes", "webServer", "visitors"])
def test_a_part_the_hub_does_not_name_is_left_out(left_out):
    assert left_out not in rendered()


def test_the_proxys_plugin_and_every_other_tunnel_are_left_out():
    proxies = rendered()["proxies"]

    assert [proxy["name"] for proxy in proxies] == ["neutrino"]
    assert "plugin" not in proxies[0]


def test_the_tunnel_of_the_name_is_taken_from_a_nodes_config():
    proxies = rendered(OPENFRP_NODE_CONFIG, port=18444)["proxies"]

    assert proxies == [
        {
            "name": "neutrino",
            "type": "tcp",
            "remotePort": 51607,
            "localIP": "127.0.0.1",
            "localPort": 18444,
        }
    ]


def test_a_config_without_the_tunnel_is_refused():
    with pytest.raises(ValueError):
        render_frpc(SAKURAFRP_CONFIG, tunnel_name="gone", loopback_port=18443)


def test_text_that_is_not_toml_is_refused():
    with pytest.raises(ValueError):
        render_frpc("[common]\nserver_addr = x\n[[", tunnel_name="x", loopback_port=1)


def test_a_string_with_quotes_and_a_line_break_stays_one_value():
    text = 'user = "a\\"b\\nc"\n[[proxies]]\nname = "n"\ntype = "tcp"\n'

    assert rendered(text, name="n")["user"] == 'a"b\nc'


def test_the_server_port_is_read_and_defaults_to_frps_own():
    assert server_port(SAKURAFRP_CONFIG) == 7001
    assert server_port('serverAddr = "x"\n') == 7000


def test_the_last_word_about_the_tunnel_decides_whether_it_was_refused():
    refused = [
        "[I] [service.go:1] login to server success",
        "[W] [control.go:2] [neutrino] start error: port already used",
    ]
    taken_later = refused + ["[I] [control.go:3] [neutrino] start proxy success"]

    assert refused_line(refused) == refused[1]
    assert refused_line(taken_later) == ""
    assert refused_line([]) == ""


@pytest.mark.parametrize(
    ("line", "state"),
    [
        (
            "[E] [service.go:9] login to the server failed: token in login "
            "doesn't match token from configuration",
            "login_failed",
        ),
        (
            "[E] login to the server failed: dial tcp 1.2.3.4:7000: connect: "
            "connection refused",
            "unreachable",
        ),
        ("[E] login to the server failed: i/o timeout", "unreachable"),
        ("[E] something else ended it", "unreachable"),
    ],
)
def test_an_ended_frpc_is_judged_by_its_last_lines(line, state):
    assert judge_exit(["[I] start frpc service", line]) == (state, line)


def test_an_ended_frpc_that_wrote_nothing_is_unreachable():
    assert judge_exit(["", "  "]) == ("unreachable", "")
