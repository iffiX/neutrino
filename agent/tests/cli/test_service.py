"""``nagent service``: the operator's walk over the Services section.

The listing is nested the way the page nests it — kind heading, numbered
entries in the state's own order — and every action addresses an entry by
that number or its id. The cells pin the words printed, the exit status,
the bodies posted (the ai apply's atomic set above all), and that a share
password reaches the agent through the terminal and never argv.
"""

import sys

import pytest

from neutrino_agent.cli import service as service_cli
from neutrino_agent.cli import wording
from neutrino_agent.control.server import ControlServer
from tests.conftest import (
    ALICE,
    ROOT,
    FakeControlAgent,
    FakeSocketPlatform,
    bind,
    discard,
)

SERVICE_ENTRIES = [
    {
        "id": "svc_wiki",
        "type": "web",
        "title": "Wiki",
        "payload": {"url": "http://wiki/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
        "modules": [],
    },
    {
        "id": "svc_down",
        "type": "web",
        "title": "Down",
        "payload": {"url": "http://down/"},
        "is_healthy": False,
        "source": "module",
        "description": "",
        "modules": [],
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "postgres",
        "payload": {"host": "hub", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "published by container postgres:16",
        "modules": [],
    },
    {
        "id": "ai",
        "type": "ai",
        "title": "AI tools",
        "payload": {
            "endpoint": "http://hub:8080",
            "protocol": "anthropic",
            "models": ["m1", "m2"],
        },
        "is_healthy": True,
        "source": "module",
        "description": "",
        "modules": ["cc_switch"],
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "media",
        "payload": {"protocol": "smb", "host": "hub", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
        "modules": ["samba_mount"],
    },
]

RDP_ENTRY = {
    "id": "rdp_s9",
    "type": "rdp",
    "title": "studio",
    "payload": {"protocol": "rustdesk", "host": "192.168.100.6", "port": 21118},
    "is_healthy": True,
    "source": "device",
    "description": "shared from studio",
    "modules": ["rustdesk"],
}
SERVICE_ENTRIES.append(RDP_ENTRY)

SERVICE_MODULES = {
    "cc_switch": {
        "title": "cc-switch",
        "description": "",
        "kind": "download",
        "entry": {"url": "https://hub/artifact"},
    },
    "samba_mount": {
        "title": "Share mounting",
        "description": "",
        "kind": "mount",
        "entry": {"packages": ["cifs-utils"]},
    },
    "rustdesk": {
        "title": "RustDesk",
        "description": "",
        "kind": "rustdesk",
        "installer": "hub",
        "license": "AGPL-3.0",
        "corresponding_source": "https://example/tree/1.4.9",
        "entry": {"url": "https://hub/rustdesk.deb"},
    },
}


class FakeServiceAgent(FakeControlAgent):
    """The control agent with every service type published."""

    def __init__(self):
        super().__init__()
        self.module_state_map = {
            "cc_switch": {"state": "installed"},
            "samba_mount": {"state": "installed"},
            "rustdesk": {"state": "absent"},
        }
        self.forwards_map = {}
        self.mount_rows = []
        self.rdp_state = {
            "is_shared": False,
            "share_id": "",
            "port": 21118,
            "state": "not_shared",
            "rustdesk_id": "123456789",
            "has_password": False,
        }

    def catalog(self) -> dict:
        return {"modules": SERVICE_MODULES, "services": SERVICE_ENTRIES}

    def service_entries(self) -> list:
        return list(SERVICE_ENTRIES)

    def module_states(self) -> dict:
        return self.module_state_map

    def service_states(self) -> dict:
        return {
            "forwards": dict(self.forwards_map),
            "mounts": list(self.mount_rows),
            "rdp": dict(self.rdp_state),
        }

    def service_action(self, service_type, *, account, is_privileged, body) -> dict:
        outcome = super().service_action(
            service_type, account=account, is_privileged=is_privileged, body=body
        )
        if outcome:
            return outcome
        if service_type == "port":
            if body.get("is_enabled"):
                self.forwards_map[body["id"]] = {
                    "local_port": 15432,
                    "is_active": True,
                }
            else:
                self.forwards_map.pop(body.get("id"), None)
        if service_type == "file" and body.get("action") == "mount":
            if body.get("record_id"):
                for row in self.mount_rows:
                    if row.get("record_id") == body["record_id"]:
                        row["state"] = "queued"
            else:
                self.mount_rows.append(
                    {
                        "record_id": "r_cfg",
                        "entry_id": body.get("id"),
                        "path": body.get("path"),
                        "account": account,
                        "username": body.get("username"),
                        "is_attached": False,
                        "state": "queued",
                        "code": "",
                        "params": {},
                    }
                )
        if service_type == "file" and body.get("action") == "unmount":
            for row in self.mount_rows:
                if row.get("record_id") == body.get("record_id"):
                    row["state"] = "detached"
                    row["is_attached"] = False
        return {}


class FakeBrowser:
    """A browser that only remembers what it was asked to open."""

    def __init__(self):
        self.opened = []

    def open(self, url) -> bool:
        self.opened.append(url)
        return True


class FakeGetpass:
    """A terminal password ask that answers from the script."""

    def __init__(self, secret: str):
        self.secret = secret
        self.prompts = []

    def getpass(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.secret


MOUNTED_ROW = {
    "record_id": "r1",
    "entry_id": "share_media",
    "path": "/home/alice/nas/media",
    "account": "alice",
    "username": "alice",
    "is_attached": True,
    "state": "mounted",
    "code": "",
    "params": {},
}


@pytest.fixture
def stack(tmp_path, monkeypatch, config_path):
    """One running control server on a bound machine, asked as root."""
    platform = FakeSocketPlatform(str(tmp_path / "agent.sock"))
    agent = FakeServiceAgent()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    assert server.socket_path
    platform.peer = dict(ROOT)
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    bind(config_path)
    yield agent, platform
    server.stop()


# --- the nested listing ---


def test_list_nests_by_kind_and_numbers_per_kind(stack, capsys):
    agent, _ = stack
    agent.forwards_map["svc_tcp"] = {"local_port": 15432, "is_active": True}
    agent.mount_rows.append(dict(MOUNTED_ROW))

    assert service_cli.main_list() == 0

    out = capsys.readouterr().out
    for heading in ("Web", "Ports", "AI", "Files"):
        assert f"{heading}\n  1  " in out
    assert "  2  Down" in out
    assert "not reachable now" in out
    assert "hub:5432 -> 127.0.0.1:15432" in out
    assert "declared by hand" in out
    assert "/home/alice/nas/media (alice) — mounted" in out
    assert "\x1b" not in out


def test_list_words_the_missing_modules_under_the_entry(stack, capsys):
    agent, _ = stack
    agent.module_state_map["cc_switch"] = {"state": "absent"}

    assert service_cli.main_list() == 0

    out = capsys.readouterr().out
    assert (
        "these modules are missing: cc-switch — nagent module install cc_switch" in out
    )


def test_list_says_when_the_machine_joined_no_gateway(stack, config_path, capsys):
    config_path.write_text("{}")

    assert service_cli.main_list() == 1

    assert wording.NOT_JOINED in capsys.readouterr().out


def test_list_says_when_the_agent_is_dead(tmp_path, monkeypatch, capsys):
    platform = FakeSocketPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)

    assert service_cli.main_list() == 1

    assert wording.AGENT_NOT_RUNNING in capsys.readouterr().err


# --- web ---


def test_web_open_resolves_by_number_and_by_id(stack, monkeypatch, capsys):
    browser = FakeBrowser()
    monkeypatch.setattr(service_cli, "webbrowser", browser)

    assert service_cli.main_web_open("1") == 0
    assert service_cli.main_web_open("svc_wiki") == 0

    assert browser.opened == ["http://wiki/", "http://wiki/"]
    assert "opening http://wiki/" in capsys.readouterr().out


def test_web_open_refuses_an_unhealthy_entry(stack, monkeypatch, capsys):
    browser = FakeBrowser()
    monkeypatch.setattr(service_cli, "webbrowser", browser)

    assert service_cli.main_web_open("2") == 1

    assert browser.opened == []
    assert service_cli.SERVICE_UNHEALTHY in capsys.readouterr().err


def test_an_unknown_ref_resolves_to_nothing(stack, capsys):
    assert service_cli.main_web_open("9") == 2

    assert "no web entry 9" in capsys.readouterr().err


# --- port ---


def test_port_forward_posts_the_pages_body_and_prints_the_loopback(stack, capsys):
    agent, _ = stack

    assert service_cli.main_port("1", is_enabled=True) == 0

    assert agent.service_calls == [
        ("port", "root", True, {"id": "svc_tcp", "is_enabled": True})
    ]
    assert "127.0.0.1:15432" in capsys.readouterr().out


def test_port_unforward_closes_and_names_the_loopback(stack, capsys):
    agent, _ = stack
    agent.forwards_map["svc_tcp"] = {"local_port": 15432, "is_active": True}

    assert service_cli.main_port("1", is_enabled=False) == 0

    assert agent.service_calls == [
        ("port", "root", True, {"id": "svc_tcp", "is_enabled": False})
    ]
    assert "closed 127.0.0.1:15432" in capsys.readouterr().out


def test_port_unforward_with_no_forward_posts_nothing(stack, capsys):
    agent, _ = stack

    assert service_cli.main_port("1", is_enabled=False) == 0

    assert agent.service_calls == []
    assert "no forward is running" in capsys.readouterr().out


def test_a_typed_refusal_is_worded_by_the_cli_table(stack, capsys):
    agent, _ = stack
    agent.service_reply = {"code": "forward_failed", "params": {"detail": "in use"}}

    assert service_cli.main_port("1", is_enabled=True) == 1

    assert "in use" in capsys.readouterr().err


# --- file ---


def test_file_config_asks_the_terminal_and_never_argv(stack, monkeypatch, capsys):
    agent, _ = stack
    asked = FakeGetpass("s3cret")  # scan: allow
    monkeypatch.setattr(service_cli, "getpass", asked)

    code = service_cli.main_file_config(
        "1", path="/home/alice/nas/media", username="alice"
    )

    assert code == 0
    assert asked.prompts == ["Share password: "]  # scan: allow
    kind, account, is_privileged, body = agent.service_calls[0]
    assert (kind, account, is_privileged) == ("file", "root", True)
    assert body == {
        "action": "mount",
        "id": "share_media",
        "username": "alice",
        "password": asked.secret,  # scan: allow
        "path": "/home/alice/nas/media",
    }
    assert asked.secret not in " ".join(sys.argv)
    out = capsys.readouterr().out
    assert asked.secret not in out
    assert "/home/alice/nas/media" in out


def test_file_config_stands_behind_the_missing_modules(stack, monkeypatch, capsys):
    agent, _ = stack
    agent.module_state_map["samba_mount"] = {"state": "absent"}
    asked = FakeGetpass("never")
    monkeypatch.setattr(service_cli, "getpass", asked)

    code = service_cli.main_file_config("1", path="/mnt/media", username="alice")

    assert code == 1
    assert asked.prompts == []
    assert agent.service_calls == []
    assert "nagent module install samba_mount" in capsys.readouterr().err


def test_file_mount_reuses_the_kept_record(stack, capsys):
    agent, _ = stack
    agent.mount_rows.append(dict(MOUNTED_ROW, is_attached=False, state="detached"))

    assert service_cli.main_file_mount("1") == 0

    assert agent.service_calls == [
        ("file", "root", True, {"action": "mount", "record_id": "r1"})
    ]
    assert wording.CLI_MOUNT_STATE_WORDS["queued"] in capsys.readouterr().out


def test_file_mount_without_a_record_points_at_config(stack, capsys):
    agent, _ = stack

    assert service_cli.main_file_mount("1") == 1

    assert agent.service_calls == []
    assert service_cli.SERVICE_NO_RECORD in capsys.readouterr().err


def test_file_mount_of_an_attached_record_posts_nothing(stack, capsys):
    agent, _ = stack
    agent.mount_rows.append(dict(MOUNTED_ROW))

    assert service_cli.main_file_mount("1") == 0

    assert agent.service_calls == []
    assert "already mounted at /home/alice/nas/media" in capsys.readouterr().out


def test_file_unmount_detaches_and_words_the_record(stack, capsys):
    agent, _ = stack
    agent.mount_rows.append(dict(MOUNTED_ROW))

    assert service_cli.main_file_unmount("1") == 0

    assert agent.service_calls == [
        ("file", "root", True, {"action": "unmount", "record_id": "r1"})
    ]
    assert wording.CLI_MOUNT_STATE_WORDS["detached"] in capsys.readouterr().out


# --- ai ---


def test_ai_show_draws_every_chip_for_a_privileged_caller(stack, capsys):
    assert service_cli.main_ai_show() == 0

    out = capsys.readouterr().out
    assert "AI tools  http://hub:8080" in out
    assert "alice" in out and "on " in out
    assert "bob" in out and "off" in out
    assert "not installed" in out


def test_ai_show_scopes_an_ordinary_caller_to_their_own_chip(stack, capsys):
    _, platform = stack
    platform.peer = dict(ALICE)

    assert service_cli.main_ai_show() == 0

    out = capsys.readouterr().out
    assert "alice" in out
    assert "bob" not in out


def test_ai_apply_commits_the_whole_target_set(stack, capsys):
    agent, _ = stack

    code = service_cli.main_ai_apply(
        ["alice"],
        claude_default=None,
        claude_opus="m2",
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 0
    assert agent.service_calls == [
        (
            "ai",
            "root",
            True,
            {
                "targets": {"alice": True, "bob": False},
                "tool_configs": {
                    "claude": {"default": "m1", "opus": "m2"},
                    "codex": {},
                    "gemini": {},
                },
            },
        )
    ]
    out = capsys.readouterr().out
    assert "switched at the gateway: alice" in out
    assert "put back: bob" in out


def test_ai_apply_with_no_accounts_disables_everyone(stack, capsys):
    agent, _ = stack

    code = service_cli.main_ai_apply(
        [],
        claude_default=None,
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 0
    assert agent.service_calls[0][3]["targets"] == {"alice": False, "bob": False}
    assert "switched at the gateway: nobody" in capsys.readouterr().out


def test_ai_apply_refuses_an_account_this_machine_does_not_have(stack, capsys):
    agent, _ = stack

    code = service_cli.main_ai_apply(
        ["carol"],
        claude_default=None,
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 2
    assert agent.service_calls == []
    assert "no account carol on this machine" in capsys.readouterr().err


def test_ai_apply_refuses_a_model_the_gateway_does_not_serve(stack, capsys):
    agent, _ = stack

    code = service_cli.main_ai_apply(
        ["alice"],
        claude_default="m9",
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 2
    assert agent.service_calls == []
    assert "no model m9 at the gateway; it serves: m1, m2" in capsys.readouterr().err


def test_ai_apply_stands_behind_the_missing_modules(stack, capsys):
    agent, _ = stack
    agent.module_state_map["cc_switch"] = {"state": "absent"}

    code = service_cli.main_ai_apply(
        ["alice"],
        claude_default=None,
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 1
    assert agent.service_calls == []
    assert "nagent module install cc_switch" in capsys.readouterr().err


# --- nagent service rdp: share here, connect there ---


def test_the_listing_nests_remote_desktops_under_their_own_heading(stack, capsys):
    assert service_cli.main_list() == 0

    out = capsys.readouterr().out
    assert "Remote desktops" in out
    assert "studio" in out
    assert "192.168.100.6:21118" in out


def test_share_asks_the_password_on_the_terminal_and_never_argv(
    stack, monkeypatch, capsys
):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}
    monkeypatch.setattr(service_cli.getpass, "getpass", lambda prompt: "hunter2")

    assert service_cli.main_rdp_share() == 0

    kind, _account, _is_privileged, body = agent.service_calls[-1]
    assert kind == "rdp"
    assert body == {"action": "share", "password": "hunter2"}
    # It was read from the terminal, so it is on no command line at all.
    assert "hunter2" not in " ".join(sys.argv)


def test_sharing_without_the_module_names_the_command_that_installs_it(stack, capsys):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "absent", "title": "RustDesk"}

    assert service_cli.main_rdp_share() == 1

    assert agent.service_calls == []
    assert "nagent module install rustdesk" in capsys.readouterr().err


def test_share_with_an_empty_password_asks_the_agent_nothing(
    stack, monkeypatch, capsys
):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}
    monkeypatch.setattr(service_cli.getpass, "getpass", lambda prompt: "")

    assert service_cli.main_rdp_share() == 2

    assert agent.service_calls == []
    assert "access password" in capsys.readouterr().err


def test_unshare_posts_the_pages_own_ask(stack, capsys):
    agent, _ = stack
    agent.rdp_state["is_shared"] = True
    agent.rdp_state["state"] = "sharing"

    assert service_cli.main_rdp_unshare() == 0

    kind, _account, _is_privileged, body = agent.service_calls[-1]
    assert (kind, body) == ("rdp", {"action": "unshare"})
    assert "not shared" in capsys.readouterr().out


def test_unsharing_what_is_not_shared_asks_the_agent_nothing(stack, capsys):
    agent, _ = stack

    assert service_cli.main_rdp_unshare() == 0

    assert agent.service_calls == []


def test_connect_addresses_an_entry_by_its_number(stack, capsys):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}

    assert service_cli.main_rdp_connect("1") == 0

    kind, _account, _is_privileged, body = agent.service_calls[-1]
    assert kind == "rdp"
    assert body == {"action": "connect", "id": "rdp_s9"}
    assert "192.168.100.6:21118" in capsys.readouterr().out


def test_connect_addresses_an_entry_by_its_id(stack, capsys):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}

    assert service_cli.main_rdp_connect("rdp_s9") == 0

    assert agent.service_calls[-1][3]["id"] == "rdp_s9"


def test_connecting_to_an_entry_nobody_published_is_refused(stack, capsys):
    agent, _ = stack

    assert service_cli.main_rdp_connect("9") == 2

    assert agent.service_calls == []
    assert "no rdp entry 9" in capsys.readouterr().err


def test_show_prints_where_this_machines_own_share_stands(stack, capsys):
    agent, _ = stack
    agent.rdp_state.update({"is_shared": True, "state": "sharing"})

    assert service_cli.main_rdp_show() == 0

    out = capsys.readouterr().out
    assert "shared" in out
    assert "123456789" in out


def test_show_says_plainly_when_nothing_is_shared(stack, capsys):
    assert service_cli.main_rdp_show() == 0

    assert "not shared" in capsys.readouterr().out


def test_a_refused_share_is_worded_from_the_agents_code(stack, monkeypatch, capsys):
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}
    monkeypatch.setattr(service_cli.getpass, "getpass", lambda prompt: "hunter2")
    agent.service_reply = {"code": "rdp_configure_failed", "params": {"detail": "no"}}

    assert service_cli.main_rdp_share() == 1

    assert "RustDesk could not be configured" in capsys.readouterr().err


def test_share_names_the_desktop_it_is_for_when_told_whose(stack, monkeypatch, capsys):
    """`--user` rides the body as the page's chip does; unnamed, the agent
    itself falls back to the one account at the screen."""
    agent, _ = stack
    agent.module_state_map["rustdesk"] = {"state": "installed"}
    monkeypatch.setattr(service_cli.getpass, "getpass", lambda prompt: "hunter2")

    assert service_cli.main_rdp_share(user="pat") == 0

    kind, _account, _is_privileged, body = agent.service_calls[-1]
    assert kind == "rdp"
    assert body == {"action": "share", "password": "hunter2", "account": "pat"}


def test_file_config_names_the_account_the_mount_is_for(stack, monkeypatch):
    agent, _ = stack
    asked = FakeGetpass("s3cret")  # scan: allow
    monkeypatch.setattr(service_cli, "getpass", asked)

    code = service_cli.main_file_config(
        "1", path="/home/pat/nas/media", username="alice", user="pat"
    )

    assert code == 0
    _kind, _account, _is_privileged, body = agent.service_calls[0]
    assert body["account"] == "pat"
