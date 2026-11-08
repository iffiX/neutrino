"""The file routes, each one ``file`` stream on the device's agent.

What these pin: the listing route over scripted streams, opened as
``file {op: list, path}``, the listing read from the agent's entries, one
JSON entry per ``data`` record, with directories first and the machine's
separator from the close, a folder of 3,000 entries and over 300 KB whole, a
line that does not read left out, a Windows root as its drives, a device with
no channel answered 409, and the agent's typed codes mapped to 400 and 404.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.agent import file as device_files
from tests.conftest import FakeChannelSessions

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRuntime:
    def __init__(self):
        self.agent_sessions = FakeChannelSessions(online=[MAC])
        self.device_platform: dict = {}


@pytest.fixture
def served():
    app = FastAPI()
    app.include_router(device_files.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime


@pytest.fixture
def api(served):
    client, runtime = served
    return client, runtime.agent_sessions


def done(**fields) -> dict:
    return {"code": "", "params": fields}


def listing(entries: list, **fields) -> tuple:
    """A listing as the agent sends it: one ``data`` record per entry, then the close."""
    records = [
        ("data", (json.dumps(entry, separators=(",", ":")) + "\n").encode("utf-8"))
        for entry in entries
    ]
    return records, done(**fields)


def refused(code: str, **params) -> dict:
    return {"code": code, "params": params}


def opened(sessions) -> list:
    """Every ``file`` stream the route opened, in order."""
    return [stream for stream in sessions.streams if stream.kind == "file"]


# --- listing ---


def test_a_listing_is_the_agents_entries_directories_first(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: listing(
        [
            {
                "name": "b.txt",
                "path": "/srv/b.txt",
                "kind": "file",
                "size": 5,
                "modified_at": 100,
                "mode": 0o644,
            },
            {"name": "link", "kind": "link", "size": 0, "modified_at": 1},
            {"name": "a", "kind": "dir", "size": 0, "modified_at": 2},
        ],
        path="/srv",
        separator="/",
    )

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "/srv"})

    assert answer.status_code == 200
    assert answer.json() == {
        "path": "/srv",
        "separator": "/",
        "entries": [
            {
                "name": "a",
                "path": "",
                "is_dir": True,
                "is_link": False,
                "size_bytes": 0,
                "modified_at": 2,
            },
            {
                "name": "b.txt",
                "path": "/srv/b.txt",
                "is_dir": False,
                "is_link": False,
                "size_bytes": 5,
                "modified_at": 100,
            },
            {
                "name": "link",
                "path": "",
                "is_dir": False,
                "is_link": True,
                "size_bytes": 0,
                "modified_at": 1,
            },
        ],
    }
    (stream,) = opened(sessions)
    assert stream.args == {"op": "list", "path": "/srv"}


def test_a_folder_of_3000_entries_over_300_kb_lists_whole(api):
    client, sessions = api
    entries = [
        {
            "name": f"program-with-a-long-name-{n:04d}",
            "path": f"/usr/bin/program-with-a-long-name-{n:04d}",
            "kind": "dir" if n % 10 == 0 else "file",
            "size": n,
            "modified_at": 1_700_000_000 + n,
            "mode": 0o755,
        }
        for n in range(3000)
    ]
    records, close = listing(entries, path="/usr/bin", separator="/")
    sessions.scripts["file"] = lambda args: (records, close)

    answer = client.get(
        "/api/agent/file", params={"device_id": MAC, "path": "/usr/bin"}
    )

    assert sum(len(record[1]) for record in records) > 300_000
    assert answer.status_code == 200
    listed = answer.json()
    assert (listed["path"], listed["separator"]) == ("/usr/bin", "/")
    assert len(listed["entries"]) == 3000
    expected = sorted(entries, key=lambda e: (e["kind"] != "dir", e["name"]))
    assert [e["name"] for e in listed["entries"]] == [e["name"] for e in expected]
    assert listed["entries"][-1] == {
        "name": "program-with-a-long-name-2999",
        "path": "/usr/bin/program-with-a-long-name-2999",
        "is_dir": False,
        "is_link": False,
        "size_bytes": 2999,
        "modified_at": 1_700_002_999,
    }


def test_a_line_that_does_not_read_is_left_out(api):
    client, sessions = api
    records, close = listing(
        [{"name": "a", "kind": "file", "size": 1, "modified_at": 1}], path="/srv"
    )
    sessions.scripts["file"] = lambda args: (
        [("data", b'{"name":"cut\xe2\x80\xa6\n')] + records,
        close,
    )

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "/srv"})

    assert [e["name"] for e in answer.json()["entries"]] == ["a"]


def test_no_path_lists_the_root(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: listing([], path="/")

    assert client.get("/api/agent/file", params={"device_id": MAC}).status_code == 200
    assert opened(sessions)[0].args == {"op": "list", "path": "/"}


WINDOWS = {"os": "windows", "arch": "x86_64"}


def test_a_windows_root_is_its_drives_with_their_own_paths(served):
    client, runtime = served
    runtime.device_platform[MAC] = WINDOWS
    drive = {"kind": "dir", "size": 0, "modified_at": 0, "mode": 0}
    runtime.agent_sessions.scripts["file"] = lambda args: listing(
        [dict(drive, name="D:", path="D:\\"), dict(drive, name="C:", path="C:\\")],
        path="/",
        separator="\\",
    )

    answer = client.get("/api/agent/file", params={"device_id": MAC})

    assert answer.json()["path"] == "/"
    assert answer.json()["separator"] == "\\"
    assert [(e["name"], e["path"]) for e in answer.json()["entries"]] == [
        ("C:", "C:\\"),
        ("D:", "D:\\"),
    ]
    assert opened(runtime.agent_sessions)[0].args == {"op": "list", "path": "/"}


@pytest.mark.parametrize("platform, separator", [(WINDOWS, "\\"), ({}, "/")])
def test_an_agent_that_names_no_separator_gets_its_platforms(
    served, platform, separator
):
    client, runtime = served
    runtime.device_platform[MAC] = platform
    runtime.agent_sessions.scripts["file"] = lambda args: listing([], path="C:\\Users")

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "C:\\"})

    assert answer.json()["separator"] == separator


def test_a_device_with_no_channel_answers_409(api):
    client, sessions = api
    sessions.online.clear()

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "/"})

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"


def test_a_close_carrying_a_code_is_the_agents_refusal(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: ([], refused("path_missing", path="/nope"))

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "/nope"})

    assert answer.status_code == 404
    assert answer.json()["detail"] == {
        "code": "path_missing",
        "params": {"path": "/nope"},
    }


def test_each_code_answers_on_its_own_status(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: ([], refused("op_failed", path="/x"))

    answer = client.get("/api/agent/file", params={"device_id": MAC, "path": "/x"})

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "op_failed"


# --- download ---
