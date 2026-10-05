"""The relay's start line, and the state an ended ssh leaves.

The start line is the one network.md gives, word for word; an exit is
judged by the last line ssh wrote, from the table in the overlay module's
constants.
"""

import pytest

from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig
from neutrino_hub.modules.overlay.relay_renderer import (
    OverlayRelayRenderer,
    judge_exit,
)

RELAY = OverlayRelayConfig(
    is_enabled=True,
    host="203.0.113.5",
    ssh_port=2222,
    account="relay",
    key_id="k1",
    public_port=18443,
)


def renderer() -> OverlayRelayRenderer:
    return OverlayRelayRenderer(
        ssh_path="/usr/bin/ssh",
        key_path="/var/lib/neutrino/hub/relay/key",
        known_hosts_path="/var/lib/neutrino/hub/relay/known_hosts",
        agent_port=8443,
    )


def test_the_start_line_is_the_one_the_standard_gives():
    assert renderer().render(RELAY) == [
        "/usr/bin/ssh",
        "-N",
        "-T",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=/var/lib/neutrino/hub/relay/known_hosts",
        "-i",
        "/var/lib/neutrino/hub/relay/key",
        "-p",
        "2222",
        "-R",
        "0.0.0.0:18443:127.0.0.1:8443",
        "relay@203.0.113.5",
    ]


def test_a_relay_with_no_host_account_or_key_renders_nothing():
    with pytest.raises(ValueError):
        renderer().render(OverlayRelayConfig(host="vps", account="relay"))


@pytest.mark.parametrize(
    ("lines", "state"),
    [
        (
            [
                "Warning: Permanently added '[203.0.113.5]:2222' (ED25519) to the "
                "list of known hosts.",
                "relay@203.0.113.5: Permission denied (publickey).",
            ],
            "auth_failed",
        ),
        (
            [
                "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
                "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @",
                "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
                "Host key for [203.0.113.5]:2222 has changed and you have requested "
                "strict checking.",
                "Host key verification failed.",
            ],
            "host_key_changed",
        ),
        (
            ["Error: remote port forwarding failed for listen port 18443"],
            "forward_refused",
        ),
        (
            ["ssh: connect to host 203.0.113.5 port 2222: Connection refused"],
            "unreachable",
        ),
        (["Timeout, server 203.0.113.5 not responding."], "unreachable"),
        (
            ["ssh: Could not resolve hostname vps: Name or service not known"],
            "unreachable",
        ),
    ],
)
def test_each_exit_is_judged_by_the_last_line_ssh_wrote(lines, state):
    judged, last = judge_exit(lines)

    assert judged == state
    assert last == lines[-1]


def test_an_older_line_does_not_decide_a_later_exit():
    lines = [
        "relay@203.0.113.5: Permission denied (publickey).",
        "ssh: connect to host 203.0.113.5 port 2222: Connection refused",
    ]

    assert judge_exit(lines)[0] == "unreachable"


def test_an_exit_with_no_output_is_unreachable_with_no_line():
    assert judge_exit(["", "  "]) == ("unreachable", "")


def test_a_key_file_ssh_ignored_for_its_permissions_is_not_auth_failed():
    """ssh ends such a run with `Permission denied`; the fault is the hub's own
    file, so the state is not the one that tells the owner to check the key."""
    lines = [
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
        "@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
        "Permissions for 'C:\\\\ProgramData\\\\Neutrino\\\\hub\\\\state\\\\relay\\\\key' "
        "are too open.",
        "This private key will be ignored.",
        'Load key "C:\\\\ProgramData\\\\Neutrino\\\\hub\\\\state\\\\relay\\\\key": '
        "bad permissions",
        "relay@203.0.113.5: Permission denied (publickey).",
    ]

    state, last_error = judge_exit(lines)

    assert state == "unreachable"
    assert last_error.startswith("the hub's own key file can be read by other")
    assert last_error.endswith("bad permissions")
