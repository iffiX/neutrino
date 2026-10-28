"""``nclient file``: list, mount and unmount against a scripted client.

A share is ``<machine>/<share>``, the share left out where the machine has
one. A machine's share mounts with no question at the default place or the
one given; a declared share asks its user name and password at the
terminal, never on the command line. Both wait for the record to settle
and print where it stands, or its failure's words.
"""

import pytest

from neutrino_client.cli import file, wording

MACHINE_SHARE = "share_d1_alice"


def test_list_prints_each_machines_shares_and_where_they_are(running, capsys):
    assert file.main_list() == 0

    assert capsys.readouterr().out.splitlines() == [
        "lab-gpu",
        "  alice  /home/alice/remote/lab-gpu-alice  mounted",
        "192.168.1.9",
        "  media  -  not mounted",
    ]


def test_list_speaks_chinese(running, chinese, capsys):
    assert file.main_list() == 0
    assert (
        "  alice  /home/alice/remote/lab-gpu-alice  已挂载" in capsys.readouterr().out
    )


def test_a_machines_share_mounts_with_no_question(running, monkeypatch, capsys):
    running.state["mounts"] = []
    monkeypatch.setattr(wording, "ask_text", _never)

    def mounted(state):
        state["mounts"] = [
            {
                "record_id": "r9",
                "hub_id": "h1",
                "entry_id": MACHINE_SHARE,
                "path": "/home/alice/remote/lab-gpu-alice",
                "state": "mounted",
                "is_attached": True,
                "code": "",
                "params": {},
            }
        ]

    running.answers["/api/services/file"] = _then(running, mounted)

    assert file.main_mount("lab-gpu") == 0

    assert running.posts("/api/services/file") == [
        {"action": "mount", "hub_id": "h1", "id": MACHINE_SHARE, "path": ""}
    ]
    assert capsys.readouterr().out.strip() == (
        "/home/alice/remote/lab-gpu-alice: mounted"
    )


def test_the_place_given_goes_with_the_mount(running):
    running.state["mounts"] = []

    assert file.main_mount("lab-gpu/alice", path="/mnt/alice") == 0
    assert file.main_mount("lab-gpu", drive="Z:") == 0

    assert [body["path"] for body in running.posts("/api/services/file")] == [
        "/mnt/alice",
        "Z:",
    ]


def test_a_mounted_share_is_said_and_not_mounted_again(running, capsys):
    assert file.main_mount("lab-gpu") == 0

    assert running.posts("/api/services/file") == []
    assert "mounted" in capsys.readouterr().out


def test_a_detached_record_mounts_again_at_its_place(running):
    running.state["mounts"][0].update(state="detached", is_attached=False)

    assert file.main_mount("lab-gpu") == 0
    assert running.posts("/api/services/file") == [
        {"action": "mount", "hub_id": "h1", "record_id": "r1"}
    ]


def test_a_declared_share_asks_its_login_at_the_terminal(running, monkeypatch):
    asked = []
    monkeypatch.setattr(
        wording, "ask_text", lambda prompt: asked.append(prompt) or "nas"
    )
    monkeypatch.setattr(
        wording, "ask_secret", lambda prompt: asked.append(prompt) or "pw"
    )

    assert file.main_mount("192.168.1.9/media") == 0

    assert asked == ["User name for media: ", "Password for media: "]
    assert running.posts("/api/services/file") == [
        {
            "action": "mount",
            "hub_id": "h1",
            "id": "nas_file_media",
            "path": "",
            "username": "nas",
            "password": "pw",
        }
    ]


def test_a_declared_share_with_no_user_name_is_not_mounted(
    running, monkeypatch, capsys
):
    monkeypatch.setattr(wording, "ask_text", lambda prompt: "")

    assert file.main_mount("192.168.1.9") == 1
    assert running.posts("/api/services/file") == []
    assert capsys.readouterr().err.strip() == wording.line("user_missing")


def test_a_declared_share_refused_its_login_asks_a_new_one(running, monkeypatch):
    running.state["mounts"].append(
        {
            "record_id": "r2",
            "hub_id": "h1",
            "entry_id": "nas_file_media",
            "path": "/home/alice/remote/192-168-1-9-media",
            "state": "failed",
            "is_attached": False,
            "code": "share_login_rejected",
            "params": {},
        }
    )
    monkeypatch.setattr(wording, "ask_text", lambda prompt: "nas")
    monkeypatch.setattr(wording, "ask_secret", lambda prompt: "right")
    running.answers["/api/services/file"] = _then(running, _mounted_r2)

    assert file.main_mount("192.168.1.9/media") == 0
    assert running.posts("/api/services/file") == [
        {
            "action": "set",
            "hub_id": "h1",
            "record_id": "r2",
            "username": "nas",
            "password": "right",
        }
    ]


def test_a_mount_that_failed_prints_its_words_and_exits_1(running, capsys):
    running.state["mounts"] = []

    def failed(state):
        state["mounts"] = [
            {
                "record_id": "r9",
                "hub_id": "h1",
                "entry_id": MACHINE_SHARE,
                "path": "/x",
                "state": "failed",
                "is_attached": False,
                "code": "pkexec_missing",
                "params": {},
            }
        ]

    running.answers["/api/services/file"] = _then(running, failed)

    assert file.main_mount("lab-gpu") == 1
    assert capsys.readouterr().err.strip() == wording.word_code("pkexec_missing")


def test_a_mount_waits_while_the_record_is_at_work(running):
    running.state["mounts"] = []
    reads = []

    def working(state):
        reads.append(1)
        state["mounts"] = [
            {
                "record_id": "r9",
                "hub_id": "h1",
                "entry_id": MACHINE_SHARE,
                "path": "/x",
                "state": "mounting" if len(reads) < 4 else "mounted",
                "is_attached": len(reads) >= 4,
                "code": "",
                "params": {},
            }
        ]

    running.on_state = working

    assert file.main_mount("lab-gpu") == 0
    assert len(reads) == 4


def test_a_name_that_matches_no_share_prints_the_shares(running, capsys):
    assert file.main_mount("lab-gpu/bob") == 1

    assert capsys.readouterr().err.strip() == (
        "no share named lab-gpu/bob; there are: lab-gpu/alice, 192.168.1.9/media"
    )


def test_unmount_unmounts_the_mounted_record(running, capsys):
    def unmounted(state):
        state["mounts"][0].update(state="detached", is_attached=False)

    running.answers["/api/services/file"] = _then(running, unmounted)

    assert file.main_unmount("lab-gpu") == 0

    assert running.posts("/api/services/file") == [
        {"action": "unmount", "hub_id": "h1", "record_id": "r1"}
    ]
    assert capsys.readouterr().out.strip() == (
        "/home/alice/remote/lab-gpu-alice: not mounted"
    )


def test_unmount_of_a_share_not_mounted_changes_nothing(running):
    assert file.main_unmount("192.168.1.9") == 0
    assert running.posts("/api/services/file") == []


@pytest.mark.parametrize(
    "call",
    [
        lambda: file.main_list(),
        lambda: file.main_mount("lab-gpu"),
        lambda: file.main_unmount("lab-gpu"),
    ],
)
def test_no_running_client_is_client_not_running(running, capsys, call):
    running.is_running = False

    assert call() == 1
    assert capsys.readouterr().err.strip() == wording.word_code("client_not_running")


def _with_folder_share(running) -> None:
    """A folder share ``lab`` on lab-gpu, an entry for ann and one for bob."""
    for account in ("ann", "bob"):
        running.state["services"].append(
            {
                "hub_id": "h1",
                "id": f"samba_folder_d1_lab_{account}",
                "type": "file",
                "title": "lab",
                "payload": {
                    "protocol": "smb",
                    "host": "192.168.1.5",
                    "share": "lab",
                    "users": [f"neutrino-{account}"],
                    "account": account,
                },
                "is_healthy": True,
                "source": "module",
                "description": "",
                "device_id": "d1",
                "device_name": "lab-gpu",
                "is_own_machine": False,
                "job": "",
                "last_error": None,
                "mount_default": f"/home/alice/remote/lab-gpu-lab-{account}",
                "is_declared": False,
            }
        )


def test_list_prints_a_folder_share_once_per_account(running, capsys):
    _with_folder_share(running)

    assert file.main_list() == 0

    lines = capsys.readouterr().out.splitlines()
    assert "  lab (ann)  -  not mounted" in lines
    assert "  lab (bob)  -  not mounted" in lines


def test_a_folder_share_mounts_the_entry_of_the_account_named(running, capsys):
    _with_folder_share(running)

    assert file.main_mount("lab-gpu/lab", account="bob") == 0
    assert file.main_mount("lab-gpu/lab") == 1
    assert file.main_mount("lab-gpu/lab", account="eve") == 1

    assert [body["id"] for body in running.posts("/api/services/file")] == [
        "samba_folder_d1_lab_bob"
    ]
    errors = capsys.readouterr().err
    assert "lab-gpu/lab --account ann" in errors
    assert "lab-gpu/lab --account bob" in errors
    assert "eve" in errors


def test_a_folder_share_with_one_account_needs_no_account_named(running):
    _with_folder_share(running)
    running.state["services"].pop()

    assert file.main_mount("lab-gpu/lab") == 0

    assert [body["id"] for body in running.posts("/api/services/file")] == [
        "samba_folder_d1_lab_ann"
    ]


def _never(prompt):
    raise AssertionError("a machine's share asks nothing")


def _mounted_r2(state):
    for record in state["mounts"]:
        if record["record_id"] == "r2":
            record.update(state="mounted", is_attached=True, code="")


def _then(running, change):
    """An answer that changes the state the way the client would, then answers it."""

    def answer(body):
        change(running.state)
        return 200, running.state

    return answer
