"""``nclient service``: the person's walk over the Services section.

The listing is nested the way the page nests it; every action addresses an
entry by that number or its id; the cells pin the words printed, the exit
status, the bodies posted, and that a share password reaches the resident
through the terminal and never argv.
"""

import sys

import pytest

from neutrino_client.cli import service as service_cli
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from tests.conftest import FakeClientPlatform, FakeSession, bind, discard

SERVICE_ENTRIES = [
    {
        "id": "svc_wiki",
        "type": "web",
        "title": "Wiki",
        "payload": {"url": "http://wiki/"},
        "is_healthy": True,
        "source": "declared",
        "description": "declared by hand",
    },
    {
        "id": "svc_down",
        "type": "web",
        "title": "Down",
        "payload": {"url": "http://down/"},
        "is_healthy": False,
        "source": "module",
        "description": "",
    },
    {
        "id": "svc_tcp",
        "type": "port",
        "title": "postgres",
        "payload": {"host": "hub", "port": 5432},
        "is_healthy": True,
        "source": "module",
        "description": "published by container postgres:16",
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
    },
    {
        "id": "share_media",
        "type": "file",
        "title": "media",
        "payload": {"protocol": "smb", "host": "hub", "share": "media"},
        "is_healthy": True,
        "source": "module",
        "description": "",
    },
    {
        "id": "rdp_s9",
        "type": "rdp",
        "title": "studio",
        "payload": {"protocol": "rustdesk", "host": "192.168.100.6", "port": 21118},
        "is_healthy": True,
        "source": "device",
        "description": "shared from studio",
    },
]

MOUNTED_ROW = {
    "record_id": "r1",
    "entry_id": "share_media",
    "path": "/home/alice/nas/media",
    "username": "alice",
    "is_attached": True,
    "state": "mounted",
    "code": "",
    "params": {},
}


class FakeServiceSession(FakeSession):
    """The session with every service type published and reacting."""

    def __init__(self, *, platform=None):
        super().__init__(platform=platform)
        self.states = {
            "forwards": {},
            "mounts": [],
            "ai": {
                "is_enabled": False,
                "is_active": False,
                "state": "installed",
                "code": "",
                "params": {},
            },
            "ai_tool_configs": {"claude": {"default": "m1"}},
            "viewers": {},
        }

    def service_entries(self) -> list:
        return list(SERVICE_ENTRIES) if self.is_bound else []

    def service_action(self, service_type, body) -> dict:
        outcome = super().service_action(service_type, body)
        if outcome:
            return outcome
        if service_type == "port":
            if body.get("is_enabled"):
                self.states["forwards"][body["id"]] = {
                    "local_port": body.get("local_port") or 15432,
                    "is_active": True,
                }
            else:
                self.states["forwards"].pop(body.get("id"), None)
        if service_type == "file" and body.get("action") == "mount":
            if body.get("record_id"):
                for row in self.states["mounts"]:
                    if row.get("record_id") == body["record_id"]:
                        row["state"] = "queued"
            else:
                self.states["mounts"].append(
                    {
                        "record_id": "r_cfg",
                        "entry_id": body.get("id"),
                        "path": body.get("path"),
                        "username": body.get("username"),
                        "is_attached": False,
                        "state": "queued",
                        "code": "",
                        "params": {},
                    }
                )
        if service_type == "file" and body.get("action") == "unmount":
            for row in self.states["mounts"]:
                if row.get("record_id") == body.get("record_id"):
                    row["state"] = "detached"
                    row["is_attached"] = False
        if service_type == "ai":
            self.states["ai"]["is_enabled"] = bool(body.get("is_enabled"))
            self.states["ai"]["is_active"] = bool(body.get("is_enabled"))
            self.states["ai_tool_configs"] = dict(body.get("tool_configs") or {})
        return {}


class FakeGetpass:
    def __init__(self, secret: str):
        self.secret = secret
        self.prompts = []

    def getpass(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.secret


@pytest.fixture
def stack(monkeypatch, config_path):
    """One running resident on a bound person, asked as that person."""
    platform = FakeClientPlatform()
    session = FakeServiceSession(platform=platform)
    server = ControlServer(
        session=session,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    bind(config_path)
    yield session
    server.stop()


# --- the nested listing ---


def test_list_nests_by_kind_and_numbers_per_kind(stack, capsys):
    stack.states["forwards"]["svc_tcp"] = {"local_port": 15432, "is_active": True}
    stack.states["mounts"].append(dict(MOUNTED_ROW))

    assert service_cli.main_list() == 0

    out = capsys.readouterr().out
    for heading in ("Web", "Ports", "AI", "Files", "Remote desktops"):
        assert f"{heading}\n  1  " in out
    assert "  2  Down" in out
    assert "not reachable now" in out
    assert "hub:5432 -> 127.0.0.1:15432" in out
    assert "declared by hand" in out
    assert "/home/alice/nas/media: mounted" in out
    assert "192.168.100.6:21118" in out
    assert "\x1b" not in out


def test_list_says_when_the_person_joined_no_hub(stack, capsys):
    stack.is_bound = False

    assert service_cli.main_list() == 1

    assert wording.NOT_JOINED in capsys.readouterr().out


def test_list_says_when_the_resident_is_dead(monkeypatch, capsys):
    platform = FakeClientPlatform()
    platform.socket_path = platform.control_socket_path() + ".missing"
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)

    assert service_cli.main_list() == 1

    assert wording.word_code("resident_not_running") in capsys.readouterr().err


def test_list_says_when_nothing_is_published(stack, capsys):
    stack.service_entries = lambda: []

    assert service_cli.main_list() == 0

    assert service_cli.SERVICES_EMPTY in capsys.readouterr().out


# --- web ---


def test_web_open_resolves_by_number_and_by_id(stack, capsys):
    assert service_cli.main_web_open("1") == 0
    assert service_cli.main_web_open("svc_wiki") == 0

    assert stack.service_calls == [("web", {"id": "svc_wiki"})] * 2
    assert "opening http://wiki/" in capsys.readouterr().out


def test_web_open_refuses_an_unhealthy_entry(stack, capsys):
    assert service_cli.main_web_open("2") == 1

    assert stack.service_calls == []
    assert service_cli.SERVICE_UNHEALTHY in capsys.readouterr().err


def test_an_unknown_ref_resolves_to_nothing(stack, capsys):
    assert service_cli.main_web_open("9") == 2

    assert "no web entry 9" in capsys.readouterr().err


# --- port ---


def test_port_forward_posts_the_pages_body_and_prints_the_loopback(stack, capsys):
    assert service_cli.main_port("1", is_enabled=True) == 0

    assert stack.service_calls == [("port", {"id": "svc_tcp", "is_enabled": True})]
    assert "127.0.0.1:15432" in capsys.readouterr().out


def test_port_forward_carries_a_preferred_local_port(stack, capsys):
    assert service_cli.main_port("1", is_enabled=True, local_port=9000) == 0

    assert stack.service_calls == [
        ("port", {"id": "svc_tcp", "is_enabled": True, "local_port": 9000})
    ]
    assert "127.0.0.1:9000" in capsys.readouterr().out


def test_port_unforward_closes_and_names_the_loopback(stack, capsys):
    stack.states["forwards"]["svc_tcp"] = {"local_port": 15432, "is_active": True}

    assert service_cli.main_port("1", is_enabled=False) == 0

    assert stack.service_calls == [("port", {"id": "svc_tcp", "is_enabled": False})]
    assert "closed 127.0.0.1:15432" in capsys.readouterr().out


def test_port_unforward_with_no_forward_posts_nothing(stack, capsys):
    assert service_cli.main_port("1", is_enabled=False) == 0

    assert stack.service_calls == []
    assert "no forward is running" in capsys.readouterr().out


def test_a_typed_refusal_is_worded_by_the_cli_table(stack, capsys):
    stack.service_reply = {"code": "forward_failed", "params": {"detail": "in use"}}

    assert service_cli.main_port("1", is_enabled=True) == 1

    assert "in use" in capsys.readouterr().err


# --- file ---


def test_file_config_asks_the_terminal_and_never_argv(stack, monkeypatch, capsys):
    asked = FakeGetpass("s3cret")  # scan: allow
    monkeypatch.setattr(service_cli.wording, "ask_secret", asked.getpass)

    code = service_cli.main_file_config(
        "1", path="/home/alice/nas/media", username="alice"
    )

    assert code == 0
    assert asked.prompts == ["Share password: "]  # scan: allow
    kind, body = stack.service_calls[0]
    assert kind == "file"
    assert body == {
        "action": "mount",
        "id": "share_media",
        "username": "alice",
        "password": asked.secret,  # scan: allow
        "path": "/home/alice/nas/media",
    }
    assert "account" not in body
    assert asked.secret not in " ".join(sys.argv)
    out = capsys.readouterr().out
    assert asked.secret not in out
    assert "/home/alice/nas/media" in out


def test_file_mount_reuses_the_kept_record(stack, capsys):
    stack.states["mounts"].append(
        dict(MOUNTED_ROW, is_attached=False, state="detached")
    )

    assert service_cli.main_file_mount("1") == 0

    assert stack.service_calls == [("file", {"action": "mount", "record_id": "r1"})]
    assert wording.CLIENT_MOUNT_STATE_WORDS["queued"] in capsys.readouterr().out


def test_file_mount_without_a_record_points_at_config(stack, capsys):
    assert service_cli.main_file_mount("1") == 1

    assert stack.service_calls == []
    assert service_cli.SERVICE_NO_RECORD in capsys.readouterr().err


def test_file_mount_of_an_attached_record_posts_nothing(stack, capsys):
    stack.states["mounts"].append(dict(MOUNTED_ROW))

    assert service_cli.main_file_mount("1") == 0

    assert stack.service_calls == []
    assert "already mounted at /home/alice/nas/media" in capsys.readouterr().out


def test_file_unmount_detaches_and_words_the_record(stack, capsys):
    stack.states["mounts"].append(dict(MOUNTED_ROW))

    assert service_cli.main_file_unmount("1") == 0

    assert stack.service_calls == [("file", {"action": "unmount", "record_id": "r1"})]
    assert wording.CLIENT_MOUNT_STATE_WORDS["detached"] in capsys.readouterr().out


def test_a_failed_record_is_worded_from_its_code(stack, capsys):
    stack.states["mounts"].append(
        dict(
            MOUNTED_ROW,
            is_attached=False,
            state="failed",
            code="mount_not_authorized",
        )
    )

    assert service_cli.main_list() == 0

    assert wording.word_code("mount_not_authorized") in capsys.readouterr().out


# --- ai ---


def test_ai_show_prints_where_the_tools_point(stack, capsys):
    assert service_cli.main_ai_show() == 0

    out = capsys.readouterr().out
    assert "AI tools  http://hub:8080" in out
    assert f"off  {service_cli.SERVICE_AI_OFF}" in out


def test_ai_show_names_the_step_while_the_lane_works(stack, capsys):
    stack.states["ai"]["work"] = {
        "state": "working",
        "step": "switching",
        "code": "",
        "params": {},
    }

    assert service_cli.main_ai_show() == 0

    assert "(switching the tools)" in capsys.readouterr().out


def test_ai_apply_hub_posts_the_toggle_and_the_merged_knobs(stack, capsys):
    code = service_cli.main_ai_apply(
        is_enabled=True,
        claude_default="m2",
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku="",
        codex_model=None,
        codex_effort="high",
        gemini_model=None,
    )

    assert code == 0
    assert stack.service_calls == [
        (
            "ai",
            {
                "is_enabled": True,
                "tool_configs": {
                    "claude": {"default": "m2", "haiku": ""},
                    "codex": {"model_reasoning_effort": "high"},
                    "gemini": {},
                },
            },
        )
    ]
    assert f"on  {service_cli.SERVICE_AI_ON}" in capsys.readouterr().out


def test_ai_apply_off_puts_the_tools_back(stack, capsys):
    code = service_cli.main_ai_apply(
        is_enabled=False,
        claude_default=None,
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 0
    assert stack.service_calls[0][1]["is_enabled"] is False
    assert f"off  {service_cli.SERVICE_AI_OFF}" in capsys.readouterr().out


def test_ai_apply_refuses_a_model_the_gateway_does_not_serve(stack, capsys):
    code = service_cli.main_ai_apply(
        is_enabled=True,
        claude_default="m9",
        claude_opus=None,
        claude_sonnet=None,
        claude_haiku=None,
        codex_model=None,
        codex_effort=None,
        gemini_model=None,
    )

    assert code == 2
    assert stack.service_calls == []
    assert "no model m9 at the gateway; it serves: m1, m2" in capsys.readouterr().err


# --- desktop ---


def test_desktop_connect_addresses_an_entry_by_number_and_id(stack, capsys):
    assert service_cli.main_desktop_connect("1") == 0
    assert service_cli.main_desktop_connect("rdp_s9") == 0

    assert stack.service_calls == [("rdp", {"action": "connect", "id": "rdp_s9"})] * 2
    assert "opening studio" in capsys.readouterr().out


def test_desktop_connect_words_the_hubs_refusal(stack, capsys):
    stack.service_reply = {"code": "rdp_not_shared", "params": {}}

    assert service_cli.main_desktop_connect("1") == 1

    assert wording.word_code("rdp_not_shared") in capsys.readouterr().err


def test_desktop_connect_to_nothing_published_is_refused(stack, capsys):
    assert service_cli.main_desktop_connect("7") == 2

    assert "no rdp entry 7" in capsys.readouterr().err
