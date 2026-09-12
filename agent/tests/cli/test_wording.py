"""The CLI's word tables, held to the codes the agent's own source emits.

Every typed code the agent can answer with must have a wording on the
terminal surface, so a new code cannot go silent. The source is scanned for
the shape codes are emitted in, and the codes that travel some other way are
named here.
"""

import re
from pathlib import Path

import pytest

from neutrino_agent.cli import status as status_cli
from neutrino_agent.cli import wording
from neutrino_agent.rdp.constants import (
    RDP_ATTENTION_NOBODY_SEATED,
    RDP_ATTENTION_SCREEN_NOT_ALLOWED,
    RDP_STATE_NOT_SHARED,
    RDP_STATE_SHARING,
    RDP_STATE_STARTING,
)

SOURCE_DIR = Path(wording.__file__).resolve().parent.parent
CODE_PATTERN = re.compile(r'"code": "([a-z0-9_]+)"')

# The codes that reach a surface without riding a ``{"code": ...}`` literal:
# the engine records an order's failure by name, and the share says what a
# peer would wait on as a bare token.
UNSTRUCTURED_CODES = (
    "no_platform_build",
    "unknown_action",
    "unsupported_platform",
    "install_failed",
    "order_failed",
    "verify_failed",
    RDP_ATTENTION_NOBODY_SEATED,
    RDP_ATTENTION_SCREEN_NOT_ALLOWED,
)

# What a module runner refuses with, raised by name rather than emitted as
# a literal, and what the engine records against a built-in row.
MODULE_CODES = (
    "module_not_orderable",
    "samba_missing",
    "samba_config_rejected",
    "share_name_invalid",
    "share_name_reserved",
    "share_name_duplicate",
    "share_path_relative",
    "share_user_unknown",
    "user_name_invalid",
    "user_name_duplicate",
    "user_unknown",
    "command_failed",
    "port_invalid",
    "port_reserved",
    "root_url_invalid",
    "secrets_missing",
    "username_invalid",
    "admin_exists",
    "admin_unknown",
    "container_name_invalid",
    "container_name_duplicate",
    "container_unknown",
    "image_invalid",
    "port_mapping_invalid",
    "volume_invalid",
    "environment_invalid",
    "command_invalid",
    "mirror_invalid",
    "pool_name_invalid",
    "pool_name_reserved",
    "layout_unknown",
    "layout_disk_count",
    "dataset_name_invalid",
    "compression_unknown",
    "recordsize_unknown",
    "mountpoint_invalid",
    "mountpoint_forbidden",
)

# What the self-update raises, worded by the surface that shows last_error.
UPDATE_CODES = (
    "agent_package_digest_mismatch",
    "agent_update_launch_failed",
    "agent_update_fetch_failed",
)


def emitted_codes() -> set:
    """Every code the agent's own source emits in the structured shape."""
    found = set()
    for path in sorted(SOURCE_DIR.rglob("*.py")):
        found |= set(CODE_PATTERN.findall(path.read_text(encoding="utf-8")))
    return found


def is_worded(code: str) -> bool:
    """Whether either terminal surface has words for one code."""
    if wording.word_code(code, {}) not in ("", code):
        return True
    return status_cli.word_error({"code": code, "params": {}}) not in ("", code)


def test_the_scan_finds_the_codes_it_is_meant_to():
    # A scan that matched nothing would pass the completeness test silently.
    found = emitted_codes()

    assert "rdp_wrong_seat" in found
    assert "hub_unreachable" in found
    assert len(found) > 10


@pytest.mark.parametrize("code", sorted(emitted_codes()))
def test_every_code_the_agent_emits_is_worded(code):
    assert is_worded(code), f"code {code} has no CLI wording"


@pytest.mark.parametrize("code", UNSTRUCTURED_CODES + UPDATE_CODES + MODULE_CODES)
def test_every_code_that_travels_another_way_is_worded(code):
    assert is_worded(code), f"code {code} has no CLI wording"


def test_the_state_table_is_the_shares_own_tokens():
    assert set(wording.CLI_STATE_WORDS) == {
        RDP_STATE_NOT_SHARED,
        RDP_STATE_SHARING,
        RDP_STATE_STARTING,
        "unknown",
    }


def test_every_unbind_cause_the_channel_can_name_is_worded():
    for cause in ("hub_untrusted", "agent_newer_than_hub", "hub_refused"):
        assert cause in status_cli.UNBIND_CAUSE_WORDS


def test_a_code_outside_the_table_prints_as_itself():
    assert wording.word_code("some_future_code", {}) == "some_future_code"


def test_a_state_outside_the_table_reads_as_unknown():
    assert wording.word_state("some_future_state") == wording.CLI_STATE_WORDS["unknown"]


def test_a_codes_params_fill_its_wording():
    assert wording.word_code("rdp_wrong_seat", {"account": "alice"}) == (
        "alice is not signed in at this machine's screen"
    )
    assert wording.word_code("module_missing", {}) == "install the  module first"


# --- a password the person gives, never the command line ---


class _Piped:
    """A stdin that is a pipe: one line, no terminal."""

    def __init__(self, text: str):
        self.text = text

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self.text


class _Terminal:
    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        raise AssertionError("a terminal is asked without echo, never read")


def test_a_piped_secret_is_one_line_of_stdin(monkeypatch):
    """A script has a pipe and nothing else."""
    monkeypatch.setattr(wording.sys, "stdin", _Piped("hunter2\r\n"))
    monkeypatch.setattr(wording.getpass, "getpass", lambda prompt: "never")

    assert wording.ask_secret("Access password: ") == "hunter2"


def test_a_terminal_is_asked_without_echo(monkeypatch):
    prompts = []
    monkeypatch.setattr(wording.sys, "stdin", _Terminal())
    monkeypatch.setattr(
        wording.getpass, "getpass", lambda prompt: prompts.append(prompt) or "typed"
    )

    assert wording.ask_secret("Access password: ") == "typed"
    assert prompts == ["Access password: "]


def test_an_action_waits_longer_than_a_read(monkeypatch):
    """Sharing the desktop takes longer than the five seconds a read gets;
    the CLI would otherwise drop the socket and call a working share
    'not running'."""
    from neutrino_agent.constants import (
        AGENT_CONTROL_ACTION_TIMEOUT_S,
        AGENT_CONTROL_REQUEST_TIMEOUT_S,
    )

    seen = []

    def fake_request(*, socket_path, method, path, body=None, timeout_s):
        seen.append((method, path, timeout_s))
        return 200, {}

    monkeypatch.setattr(wording.client, "request", fake_request)
    monkeypatch.setattr(
        wording,
        "detect_platform",
        lambda: type("P", (), {"control_socket_path": lambda self: "/s"})(),
    )

    wording.act("/api/rdp/start", {"user": "a"})
    wording.request("GET", "/api/state")

    assert seen[0] == ("POST", "/api/rdp/start", AGENT_CONTROL_ACTION_TIMEOUT_S)
    assert seen[1] == ("GET", "/api/state", AGENT_CONTROL_REQUEST_TIMEOUT_S)
    assert AGENT_CONTROL_ACTION_TIMEOUT_S > AGENT_CONTROL_REQUEST_TIMEOUT_S
