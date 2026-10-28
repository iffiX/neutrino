"""The ``entry`` answer names each stream's row in a permission as ``key``:
a ``connect`` its entry's row, a ``shell`` or an ``exec`` its machine's
``terminal_<device id>``."""

import asyncio
from types import SimpleNamespace

from neutrino_hub.modules.clients.services import ConnectTarget
from neutrino_hub.web import channel_entry


class AgentSessions:
    def get(self, device_id):
        return SimpleNamespace(session_id=f"session-{device_id}")


def runtime():
    return SimpleNamespace(agent_sessions=AgentSessions(), settings={})


def test_a_shell_and_a_command_name_their_machines_terminal_row(monkeypatch):
    monkeypatch.setattr(
        channel_entry, "judge_terminal", lambda client, device: ("", {})
    )

    answers = [
        asyncio.run(
            channel_entry.entry_answer(
                runtime(),
                role="client",
                binding_id="c1",
                open_body={"kind": kind, "device_id": "d1"},
            )
        )
        for kind in ("shell", "exec")
    ]

    assert [(answer["kind"], answer["key"]) for answer in answers] == [
        ("terminal", "terminal_d1"),
        ("terminal", "terminal_d1"),
    ]


def test_a_connect_names_its_entrys_row_and_the_gateway_none(monkeypatch):
    targets = {
        "gitea_d1_web": ConnectTarget(
            "d1", "", 3000, kind="web", provider="d1", row_id="gitea_d1"
        ),
        "ai": ConnectTarget("", "127.0.0.1", 8317, kind="ai"),
    }
    monkeypatch.setattr(
        channel_entry,
        "connect_target",
        lambda runtime, client_id, open_body, **_: ("", {}, targets[open_body["id"]]),
    )

    answers = {
        entry_id: asyncio.run(
            channel_entry.entry_answer(
                runtime(),
                role="client",
                binding_id="c1",
                open_body={"kind": "connect", "id": entry_id},
            )
        )
        for entry_id in targets
    }

    assert answers["gitea_d1_web"]["key"] == "gitea_d1"
    assert answers["ai"]["key"] == ""
