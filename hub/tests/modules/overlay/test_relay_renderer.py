"""The relay's start line, and the state an ended ssh leaves.

The start line is the one network.md gives, word for word; an exit is
judged by the last line ssh wrote, from the table in the overlay module's
constants.
"""

import pytest

from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig
from neutrino_hub.modules.overlay.relay_renderer import (
    OverlayRelayRenderer,
    askpass_program,
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
        'UserKnownHostsFile="/var/lib/neutrino/hub/relay/known_hosts"',
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


MAC_STATE = "/Library/Application Support/Neutrino/hub/state/relay"


def spaced_renderer(state: str = MAC_STATE) -> OverlayRelayRenderer:
    return OverlayRelayRenderer(
        ssh_path="/usr/bin/ssh",
        key_path=f"{state}/key",
        known_hosts_path=f"{state}/known_hosts",
        agent_port=8443,
    )


def ssh_option_words(value: str) -> list:
    """An ``-o`` value split as ssh splits a line of ``ssh_config``."""
    import shlex

    return shlex.split(value)


def test_a_known_hosts_path_with_a_space_reaches_ssh_whole():
    """macOS keeps the state root under Application Support; ssh splits an
    unquoted -o value at the space and writes the host key beside it."""
    argv = spaced_renderer().render(RELAY)

    option = argv[argv.index("-i") - 1]
    assert ssh_option_words(option) == [f"UserKnownHostsFile={MAC_STATE}/known_hosts"]
    assert argv[argv.index("-i") + 1] == f"{MAC_STATE}/key"


def test_a_windows_known_hosts_path_keeps_its_backslashes():
    state = "C:\\ProgramData\\Neutrino\\hub\\state\\relay"
    argv = spaced_renderer(state).render(RELAY)

    option = argv[argv.index("-i") - 1]
    assert ssh_option_words(option) == [f"UserKnownHostsFile={state}/known_hosts"]


def test_the_unit_drop_in_hands_ssh_the_same_whole_path():
    """systemd reads the drop-in's quoting back into the argv the supervisor
    is handed directly, and ssh then reads the option as one path."""
    import shlex

    from neutrino_hub.system.systemd_ctl import start_line_dropin

    argv = spaced_renderer().render(RELAY)
    dropin = start_line_dropin(argv, {}, None)
    line = [row for row in dropin.splitlines() if row.startswith('ExecStart="')]

    assert shlex.split(line[0].removeprefix("ExecStart=")) == argv


# --- a relay that logs in with a password ---


def test_a_login_s_start_line_asks_a_password_once_and_offers_no_key():
    login = OverlayRelayConfig(**{**vars(RELAY), "key_id": "", "login_id": "l1"})

    argv = OverlayRelayRenderer(
        ssh_path="/usr/bin/ssh",
        key_path="/var/lib/neutrino/hub/relay/key",
        known_hosts_path="/var/lib/neutrino/hub/relay/known_hosts",
        agent_port=8443,
        askpass_path="/var/lib/neutrino/hub/relay/askpass",
    ).render(login)

    assert argv == [
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
        "BatchMode=no",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        'UserKnownHostsFile="/var/lib/neutrino/hub/relay/known_hosts"',
        "-p",
        "2222",
        "-R",
        "0.0.0.0:18443:127.0.0.1:8443",
        "relay@203.0.113.5",
    ]


def test_only_a_login_runs_with_the_askpass_environment():
    login = OverlayRelayConfig(**{**vars(RELAY), "key_id": "", "login_id": "l1"})
    made = OverlayRelayRenderer(
        ssh_path="/usr/bin/ssh",
        key_path="/k",
        known_hosts_path="/h",
        agent_port=8443,
        askpass_path="/var/lib/neutrino/hub/relay/askpass",
    )

    assert made.environment(login) == {
        "SSH_ASKPASS": "/var/lib/neutrino/hub/relay/askpass",
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": "neutrino",
    }
    assert made.environment(RELAY) == {}


@pytest.mark.parametrize(
    ("is_windows", "program"),
    [
        (False, "#!/bin/sh\nexec cat '/var/lib/neutrino hub/relay/password'\n"),
        (True, '@type "/var/lib/neutrino hub/relay/password"\r\n'),
    ],
)
def test_the_askpass_program_prints_the_password_file(is_windows, program):
    assert (
        askpass_program("/var/lib/neutrino hub/relay/password", is_windows=is_windows)
        == program
    )
