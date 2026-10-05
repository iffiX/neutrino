"""The state's ``ai_tools`` section, made true account by account.

What these pin: every account the section names is switched as itself,
with the section's endpoint, key and models, and reported switched; nothing
runs when the records already carry the settings, and a state applied once
is not applied again; an account the section no longer names, and every
account when it is off, is switched back and its records removed; an
account the machine lacks is ``account_unknown``; on Windows an account with
no login is ``credential_missing`` and the login it was switched with is
kept, root's own, for the switch back; a refusing account does not stop the
next; the report before any state is the accounts whose records stand; and
the switch back before the agent goes takes every account. cc-switch is
fetched from the hub when no copy is there or its version is not the
section's, and a copy of that version is not fetched again; a fetch the hub
refuses fails every account with ``cc_switch_download_failed`` and nothing
run, and the same state is tried again; an unreachable hub is
``hub_unreachable``; once the binding is gone no switch is made.
"""

import io
import os
import stat
import tarfile

import pytest

from neutrino_agent.ai_tools.applier import AiToolsApplier
from neutrino_agent.exceptions import ModuleApplyError
from tests.ai_tools.fake_platform import FakeAccountPlatform

HUB = "http://192.168.10.1:8317"
KEY = "device-key"  # scan: allow
CONFIGS = {"claude": {"default": "m1"}, "codex": {"model": "m2"}, "gemini": {}}


def section(*accounts, **extra):
    return {
        "is_enabled": True,
        "base_url": HUB,
        "api_key": KEY,
        "tool_configs": CONFIGS,
        "accounts": [
            {"account": name, "password": extra.get("password", "")}
            for name in accounts
        ],
    }


@pytest.fixture
def binary(tmp_path):
    """A copy of cc-switch already fetched, under each system's name."""
    directory = tmp_path / "state" / "ai_tools" / "bin"
    directory.mkdir(parents=True)
    for name in ("cc-switch", "cc-switch.exe"):
        (directory / name).write_text("")
    return str(directory / "cc-switch")


def make(tmp_path, binary=None, **platform_extra):
    platform = FakeAccountPlatform(root=str(tmp_path / "state"), **platform_extra)
    applier = AiToolsApplier(platform=platform, log=lambda line: None)
    return applier, platform


def states(applier):
    return {
        entry["account"]: (entry["state"], entry["code"])
        for entry in applier.report()["accounts"]
    }


def test_each_named_account_is_switched_as_itself(tmp_path, binary):
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )

    applier.apply(section("ann", "bob"), "h1")

    assert states(applier) == {"ann": ("switched", ""), "bob": ("switched", "")}
    assert {account for account, _password, _argv in platform.runs} == {"ann", "bob"}
    assert all(
        argv[0] == binary or argv[0] in ("cat", "test", "sh", "rm")
        for _a, _p, argv in platform.runs
    )
    added = platform.store("ann").added["claude"]
    assert "--base-url=" + HUB in added and "--api-key=" + KEY in added
    record_dir = tmp_path / "state" / "ai_tools" / "ann"
    assert sorted(os.listdir(record_dir)) == [
        "claude.json",
        "codex.json",
        "gemini.json",
    ]
    assert stat.S_IMODE(os.stat(record_dir).st_mode) == 0o700
    assert not [path for path in platform.files if path.endswith("/payload")]


def test_nothing_runs_when_nothing_changed_and_a_state_is_applied_once(
    tmp_path, binary
):
    applier, platform = make(tmp_path, binary)
    applier.apply(section("ann"), "h1")
    platform.runs.clear()

    applier.apply(section("ann"), "h1")
    applier.apply(section("ann"), "h2")

    assert platform.runs == []
    assert states(applier) == {"ann": ("switched", "")}


def test_an_account_no_longer_named_is_switched_back(tmp_path, binary):
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )
    applier.apply(section("ann", "bob"), "h1")
    platform.answered.clear()

    applier.apply(section("ann"), "h2")

    assert states(applier) == {"ann": ("switched", ""), "bob": ("switched_back", "")}
    assert not (tmp_path / "state" / "ai_tools" / "bob").exists()
    assert [answered[0] for answered in platform.answered] == ["bob"] * 3


def test_the_section_off_switches_every_account_back(tmp_path, binary):
    applier, platform = make(tmp_path, binary)
    applier.apply(section("ann"), "h1")

    applier.apply({"is_enabled": False}, "h2")

    assert states(applier) == {"ann": ("switched_back", "")}
    assert platform.store("ann").current["claude"] == "default"
    assert "neutrino" not in platform.store("ann").providers["claude"]
    assert applier.switched_accounts() == []


def test_no_section_leaves_everything_as_it_is(tmp_path, binary):
    applier, platform = make(tmp_path, binary)
    applier.apply(section("ann"), "h1")
    platform.runs.clear()

    applier.apply(None, "h2")

    assert platform.runs == []


def test_an_account_the_machine_lacks_is_account_unknown_and_the_next_still_switches(
    tmp_path, binary
):
    applier, _platform = make(tmp_path, binary)

    applier.apply(section("ghost", "ann"), "h1")

    assert states(applier) == {
        "ghost": ("failed", "account_unknown"),
        "ann": ("switched", ""),
    }


def test_a_refusing_account_keeps_its_tools_and_the_next_is_switched(tmp_path, binary):
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )
    store = platform.store("ann")
    original = store.answer

    def refuse(session, arguments, app):
        if tuple(arguments)[:2] == ("provider", "add"):
            return 1, "", "store is locked"
        return original(session, arguments, app)

    store.answer = refuse

    applier.apply(section("ann", "bob"), "h1")

    report = {entry["account"]: entry for entry in applier.report()["accounts"]}
    assert report["ann"]["state"] == "failed"
    assert report["ann"]["code"] == "switch_failed"
    assert report["ann"]["params"] == {
        "account": "ann",
        "detail": "claude: store is locked",
    }
    assert report["bob"]["state"] == "switched"
    assert store.current == {
        "claude": "default",
        "codex": "default",
        "gemini": "default",
    }


def test_a_retry_mark_tries_a_failed_account_again_and_leaves_the_others(
    tmp_path, binary
):
    """The hub's press on the chip adds ``retry_mark`` to the section; the
    state's hash moves, the failed account runs again, a switched one not."""
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )
    store = platform.store("ann")
    original = store.answer

    def refuse(session, arguments, app):
        if tuple(arguments)[:2] == ("provider", "add"):
            return 1, "", "store is locked"
        return original(session, arguments, app)

    store.answer = refuse
    applier.apply(section("ann", "bob"), "h1")
    store.answer = original
    platform.runs.clear()

    retried = section("ann", "bob")
    retried["retry_mark"] = "a1b2"
    applier.apply(retried, "h1-retry")

    assert states(applier) == {"ann": ("switched", ""), "bob": ("switched", "")}
    assert {run[0] for run in platform.runs} == {"ann"}


def test_windows_needs_the_account_s_login_and_keeps_it_for_the_switch_back(
    tmp_path, binary
):
    applier, platform = make(
        tmp_path,
        binary,
        os_name="windows",
        homes={"ann": "C:\\Users\\ann", "bob": "C:\\Users\\bob"},
    )

    applier.apply(
        {
            **section("ann"),
            "accounts": [
                {"account": "ann", "password": "pw-ann"},  # scan: allow
                {"account": "bob", "password": ""},
            ],
        },
        "h1",
    )

    assert states(applier) == {
        "ann": ("switched", ""),
        "bob": ("failed", "credential_missing"),
    }
    assert {password for _account, password, _argv in platform.runs} == {"pw-ann"}
    assert {argv[0] for _a, _p, argv in platform.runs} == {
        binary + ".exe",
        "powershell.exe",
    }
    login = tmp_path / "state" / "ai_tools" / "ann" / "login.json"
    assert stat.S_IMODE(os.stat(login).st_mode) == 0o600

    platform.runs.clear()
    applier.apply({"is_enabled": False}, "h2")

    assert states(applier) == {"ann": ("switched_back", "")}
    assert {password for _account, password, _argv, _p, _a in platform.answered} == {
        "pw-ann"
    }
    assert not login.exists()


def test_a_login_windows_refuses_is_credential_invalid(tmp_path, binary):
    applier, platform = make(tmp_path, binary, os_name="windows")
    platform.refusal = ModuleApplyError("credential_invalid", {"account": "ann"})

    applier.apply(section("ann", password="old"), "h1")

    (entry,) = applier.report()["accounts"]
    assert (entry["state"], entry["code"], entry["params"]) == (
        "failed",
        "credential_invalid",
        {"account": "ann"},
    )


def test_the_report_before_any_state_is_the_accounts_whose_records_stand(
    tmp_path, binary
):
    applier, platform = make(tmp_path, binary)
    applier.apply(section("ann"), "h1")

    restarted = AiToolsApplier(platform=platform, log=lambda line: None)

    assert restarted.report() == {
        "accounts": [{"account": "ann", "state": "switched", "code": "", "params": {}}]
    }


def test_the_switch_back_before_the_agent_goes_takes_every_account(tmp_path, binary):
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )
    applier.apply(section("ann", "bob"), "h1")

    leaving = AiToolsApplier(platform=platform, log=lambda line: None)
    results = leaving.switch_back_all()

    assert [(entry["account"], entry["state"]) for entry in results] == [
        ("ann", "switched_back"),
        ("bob", "switched_back"),
    ]
    assert leaving.switched_accounts() == []


def archive(tmp_path, *, name="cc-switch") -> str:
    """cc-switch's release archive as upstream lays it out: the program at the top."""
    path = tmp_path / "cc.tar.gz"
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo(name)
        info.size = len(b"#!cc-switch")
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(b"#!cc-switch"))
    return str(path)


class Hub:
    """The package stream, answering each ask with a path or a refusal."""

    def __init__(self, tmp_path, *, refusal=None, name="cc-switch"):
        self.asked: list = []
        self._tmp_path = tmp_path
        self._refusal = refusal
        self._name = name

    def receive(self, module):
        self.asked.append(module)
        if self._refusal is not None:
            return {"code": self._refusal, "params": {}}
        return {"path": archive(self._tmp_path, name=self._name)}


def versioned(**extra):
    return {**section("ann"), "cc_switch_version": "5.10.4", **extra}


def test_cc_switch_is_fetched_from_the_hub_and_run_from_the_state_root(tmp_path):
    applier, platform = make(tmp_path)
    hub = Hub(tmp_path)

    applier.apply(versioned(), "h1", receive=hub.receive)

    copy = tmp_path / "state" / "ai_tools" / "bin"
    assert hub.asked == ["cc_switch"]
    assert (copy / "cc-switch").read_bytes() == b"#!cc-switch"
    assert (copy / "version").read_text() == "5.10.4"
    assert platform.opened == [str(copy)]
    assert stat.S_IMODE(os.stat(copy / "cc-switch").st_mode) & 0o222 == 0
    assert not (tmp_path / "cc.tar.gz").exists()
    assert states(applier) == {"ann": ("switched", "")}
    assert {argv[0] for _a, _p, argv in platform.runs if "--app" in argv} == {
        str(copy / "cc-switch")
    }


def test_a_copy_of_the_version_named_is_not_fetched_again(tmp_path):
    applier, _platform = make(tmp_path)
    hub = Hub(tmp_path)
    applier.apply(versioned(), "h1", receive=hub.receive)

    applier.apply(versioned(base_url=HUB + "/other"), "h2", receive=hub.receive)

    assert hub.asked == ["cc_switch"]


def test_a_copy_of_another_version_is_replaced(tmp_path, binary):
    applier, _platform = make(tmp_path)
    hub = Hub(tmp_path)

    applier.apply(versioned(), "h1", receive=hub.receive)

    copy = tmp_path / "state" / "ai_tools" / "bin"
    assert hub.asked == ["cc_switch"]
    assert sorted(os.listdir(copy)) == ["cc-switch", "version"]
    assert (copy / "version").read_text() == "5.10.4"


def test_a_fetch_the_hub_refuses_fails_every_account_and_is_tried_again(tmp_path):
    applier, platform = make(tmp_path, homes={"ann": "/home/ann", "bob": "/home/bob"})
    hub = Hub(tmp_path, refusal="hub_release_file_gone")
    state = {**section("ann", "bob"), "cc_switch_version": "5.10.4"}

    applier.apply(state, "h1", receive=hub.receive)
    applier.apply(state, "h1", receive=hub.receive)

    assert hub.asked == ["cc_switch", "cc_switch"]
    assert platform.runs == []
    assert [entry for entry in applier.report()["accounts"]] == [
        {
            "account": name,
            "state": "failed",
            "code": "cc_switch_download_failed",
            "params": {"account": name, "detail": "hub_release_file_gone"},
        }
        for name in ("ann", "bob")
    ]


def test_an_archive_without_the_program_is_a_failed_download(tmp_path):
    applier, platform = make(tmp_path)

    applier.apply(versioned(), "h1", receive=Hub(tmp_path, name="other").receive)

    (entry,) = applier.report()["accounts"]
    assert entry["code"] == "cc_switch_download_failed"
    assert "cc-switch" in entry["params"]["detail"]
    assert not (tmp_path / "state" / "ai_tools" / "bin").exists()
    assert platform.runs == []


def test_an_unreachable_hub_is_said_as_it_is(tmp_path):
    applier, _platform = make(tmp_path)

    applier.apply(
        versioned(), "h1", receive=Hub(tmp_path, refusal="hub_unreachable").receive
    )

    assert states(applier) == {"ann": ("failed", "hub_unreachable")}


def test_no_switch_is_made_once_the_binding_is_gone(tmp_path, binary):
    platform = FakeAccountPlatform(root=str(tmp_path / "state"))
    applier = AiToolsApplier(
        platform=platform, log=lambda line: None, is_bound=lambda: False
    )

    applier.apply(section("ann"), "h1")

    assert platform.runs == []
    assert applier.report() == {"accounts": []}
    assert applier.switched_accounts() == []


def test_a_switch_back_with_no_copy_and_no_hub_says_the_hub_is_unreachable(
    tmp_path, binary
):
    applier, platform = make(tmp_path)
    applier.apply(section("ann"), "h1")
    applier.remove_copy()
    platform.runs.clear()

    results = applier.switch_back_all()

    assert [(entry["account"], entry["code"]) for entry in results] == [
        ("ann", "hub_unreachable")
    ]
    assert platform.runs == []
    assert applier.switched_accounts() == ["ann"]


def test_the_copy_is_removed_on_its_own(tmp_path, binary):
    applier, _platform = make(tmp_path)

    removed = applier.remove_copy()

    assert removed == [str(tmp_path / "state" / "ai_tools" / "bin")]
    assert applier.remove_copy() == []
