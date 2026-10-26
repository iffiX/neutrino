"""The file routes, each one ``file`` stream on the device's agent.

What these pin: the seven routes' paths and shapes over scripted streams,
each opened as ``file {op, path, ...}`` with its own ``op``, the listing
mapped from the agent's entries with directories first and the machine's
separator, a Windows root as its drives, a download named in the
machine's own path form and streamed as it arrives with its size only in
the close, an archive as
gzip, an upload as one multipart file pushed through the stream with its
size in the open, a device with no channel answered 409, and the agent's
typed codes mapped to 400 and 404.
"""

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


def refused(code: str, **params) -> dict:
    return {"code": code, "params": params}


def opened(sessions) -> list:
    """Every ``file`` stream the route opened, in order."""
    return [stream for stream in sessions.streams if stream.kind == "file"]


# --- listing ---


def test_a_listing_is_the_agents_entries_directories_first(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: (
        [],
        done(
            path="/srv",
            separator="/",
            entries=[
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
        ),
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


def test_no_path_lists_the_root(api):
    client, sessions = api
    sessions.scripts["file"] = lambda args: ([], done(path="/", entries=[]))

    assert client.get("/api/agent/file", params={"device_id": MAC}).status_code == 200
    assert opened(sessions)[0].args == {"op": "list", "path": "/"}


WINDOWS = {"os": "windows", "arch": "x86_64"}


def test_a_windows_root_is_its_drives_with_their_own_paths(served):
    client, runtime = served
    runtime.device_platform[MAC] = WINDOWS
    drive = {"kind": "dir", "size": 0, "modified_at": 0, "mode": 0}
    runtime.agent_sessions.scripts["file"] = lambda args: (
        [],
        done(
            path="/",
            separator="\\",
            entries=[
                dict(drive, name="D:", path="D:\\"),
                dict(drive, name="C:", path="C:\\"),
            ],
        ),
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
    runtime.agent_sessions.scripts["file"] = lambda args: (
        [],
        done(path="C:\\Users", entries=[]),
    )

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
