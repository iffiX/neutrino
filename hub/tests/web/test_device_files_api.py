"""The file routes, each one stream on the device's agent.

What these pin: the seven routes' paths and shapes over scripted streams,
the listing mapped from the agent's entries with directories first, a
download carrying the size the agent announced, an archive as gzip, an
upload as one multipart file pushed through the stream with its size in
the open, a device with no channel answered 409, and the agent's typed
codes mapped to 400 and 404.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import device_files
from tests.conftest import FakeAgentSessions

MAC = "aa:bb:cc:dd:ee:ff"


class FakeRuntime:
    def __init__(self):
        self.agent_sessions = FakeAgentSessions(online=[MAC])


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(device_files.router)
    app.dependency_overrides[require_session] = lambda: None
    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime.agent_sessions


def done(**fields) -> dict:
    return {"code": "", "params": {}, **fields}


def refused(code: str, **params) -> dict:
    return {"code": code, "params": params}


def opened(sessions, kind: str):
    return [stream for stream in sessions.streams if stream.kind == kind]


# --- listing ---


def test_a_listing_is_the_agents_entries_directories_first(api):
    client, sessions = api
    sessions.scripts["file_list"] = lambda args: (
        [],
        done(
            path="/srv",
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

    answer = client.get(f"/api/devices/{MAC}/files", params={"path": "/srv"})

    assert answer.status_code == 200
    assert answer.json() == {
        "path": "/srv",
        "entries": [
            {
                "name": "a",
                "is_dir": True,
                "is_link": False,
                "size_bytes": 0,
                "modified_at": 2,
            },
            {
                "name": "b.txt",
                "is_dir": False,
                "is_link": False,
                "size_bytes": 5,
                "modified_at": 100,
            },
            {
                "name": "link",
                "is_dir": False,
                "is_link": True,
                "size_bytes": 0,
                "modified_at": 1,
            },
        ],
    }
    (stream,) = opened(sessions, "file_list")
    assert stream.args == {"path": "/srv"}


def test_no_path_lists_the_root(api):
    client, sessions = api
    sessions.scripts["file_list"] = lambda args: ([], done(path="/", entries=[]))

    assert client.get(f"/api/devices/{MAC}/files").status_code == 200
    assert opened(sessions, "file_list")[0].args == {"path": "/"}


def test_a_device_with_no_channel_answers_409(api):
    client, sessions = api
    sessions.online.clear()

    answer = client.get(f"/api/devices/{MAC}/files", params={"path": "/"})

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"


def test_a_refused_open_carries_the_agents_code(api):
    client, sessions = api
    sessions.refusal = ("path_missing", {"path": "/nope"})

    answer = client.get(f"/api/devices/{MAC}/files", params={"path": "/nope"})

    assert answer.status_code == 404
    assert answer.json()["detail"] == {
        "code": "path_missing",
        "params": {"path": "/nope"},
    }


def test_a_close_carrying_a_code_is_refused_the_same_way(api):
    client, sessions = api
    sessions.scripts["file_list"] = lambda args: ([], refused("op_failed", path="/x"))

    answer = client.get(f"/api/devices/{MAC}/files", params={"path": "/x"})

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "op_failed"


# --- download ---


def test_a_file_download_streams_the_bytes_with_the_announced_size(api):
    client, sessions = api
    sessions.scripts["file_download"] = lambda args: (
        [("event", {"type": "event", "size": 6}), ("data", b"abc"), ("data", b"def")],
        done(size=6),
    )

    answer = client.get(
        f"/api/devices/{MAC}/files/download", params={"path": "/srv/a.bin"}
    )

    assert answer.status_code == 200
    assert answer.content == b"abcdef"
    assert answer.headers["content-length"] == "6"
    assert "a.bin" in answer.headers["content-disposition"]
    assert opened(sessions, "file_download")[0].args == {"path": "/srv/a.bin"}


def test_a_directory_download_is_an_archive_asked_for_as_one(api):
    client, sessions = api
    sessions.scripts["file_download"] = lambda args: (
        [("data", b"\x1f\x8b"), ("data", b"tar")],
        done(size=5),
    )

    answer = client.get(
        f"/api/devices/{MAC}/files/download_dir", params={"path": "/srv/.dots"}
    )

    assert answer.status_code == 200
    assert answer.content == b"\x1f\x8btar"
    assert answer.headers["content-type"] == "application/gzip"
    assert answer.headers["content-disposition"].endswith("dots.tar.gz")
    assert opened(sessions, "file_download")[0].args == {
        "path": "/srv/.dots",
        "is_archived": True,
    }


def test_a_download_of_what_is_not_there_is_404(api):
    client, sessions = api
    sessions.refusal = ("path_missing", {"path": "/srv/x"})

    answer = client.get(f"/api/devices/{MAC}/files/download", params={"path": "/srv/x"})

    assert answer.status_code == 404


# --- upload ---


def test_an_upload_is_one_file_pushed_through_the_stream(api):
    client, sessions = api
    sessions.scripts["file_upload"] = lambda args: ([], done())

    answer = client.post(
        f"/api/devices/{MAC}/files/upload",
        data={"path": "/srv/in"},
        files={"file": ("photo.jpg", b"jpegbytes", "image/jpeg")},
    )

    assert answer.status_code == 200
    assert answer.json() == {}
    (stream,) = opened(sessions, "file_upload")
    assert stream.args == {"path": "/srv/in/photo.jpg", "size": 9}
    assert stream.sent_bytes() == b"jpegbytes"


def test_an_upload_the_agent_refuses_is_typed(api):
    client, sessions = api
    sessions.scripts["file_upload"] = lambda args: (
        [],
        refused("write_failed", path="/srv/in/a", detail="oversize"),
    )

    answer = client.post(
        f"/api/devices/{MAC}/files/upload",
        data={"path": "/srv/in"},
        files={"file": ("a", b"x")},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "write_failed"


def test_an_upload_naming_a_path_instead_of_a_file_name_is_refused(api):
    client, sessions = api

    answer = client.post(
        f"/api/devices/{MAC}/files/upload",
        data={"path": "/srv"},
        files={"file": ("../etc/passwd", b"x")},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "path_invalid"
    assert sessions.streams == []


def test_an_upload_onto_a_directory_is_refused_at_the_open(api):
    client, sessions = api
    sessions.refusal = ("file_exists", {"path": "/srv/a"})

    answer = client.post(
        f"/api/devices/{MAC}/files/upload",
        data={"path": "/srv"},
        files={"file": ("a", b"x")},
    )

    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "file_exists"


# --- the operations ---


@pytest.mark.parametrize(
    "route, body, args",
    [
        ("mkdir", {"path": "/srv/new"}, {"op": "mkdir", "path": "/srv/new"}),
        (
            "rename",
            {"path": "/srv/a", "new_path": "/srv/b"},
            {"op": "rename", "path": "/srv/a", "new_path": "/srv/b"},
        ),
        ("delete", {"path": "/srv/a"}, {"op": "delete", "path": "/srv/a"}),
    ],
)
def test_each_operation_is_one_op_stream(api, route, body, args):
    client, sessions = api
    sessions.scripts["file_op"] = lambda opened_args: ([], done())

    answer = client.post(f"/api/devices/{MAC}/files/{route}", json=body)

    assert answer.status_code == 200
    assert answer.json() == {}
    assert opened(sessions, "file_op")[0].args == args


def test_an_operation_on_what_is_not_there_is_404(api):
    client, sessions = api
    sessions.scripts["file_op"] = lambda args: ([], refused("path_missing", path="/x"))

    answer = client.post(f"/api/devices/{MAC}/files/delete", json={"path": "/x"})

    assert answer.status_code == 404
    assert answer.json()["detail"] == {"code": "path_missing", "params": {"path": "/x"}}


def test_an_operation_with_no_channel_is_409(api):
    client, sessions = api
    sessions.online.clear()

    answer = client.post(f"/api/devices/{MAC}/files/mkdir", json={"path": "/x"})

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "agent_offline"
