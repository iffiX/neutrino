"""The state's ``ai_tools`` section, made true account by account.

What these pin: every account the section names is switched as itself,
with the section's endpoint, key and models, and reported switched; nothing
runs when the records already carry the settings, and a state applied once
is not applied again; an account the section no longer names, and every
account when it is off, is switched back and its records removed; a missing
cc-switch is ``bundle_missing`` for every account with nothing run; an
account the machine lacks is ``account_unknown``; on Windows an account with
no login is ``credential_missing`` and the login it was switched with is
kept, root's own, for the switch back; a refusing account does not stop the
next; the report before any state is the accounts whose records stand; and
the switch back before the agent goes takes every account.
"""

import os
import stat

import pytest

from neutrino_agent.ai_tools.applier import AiToolsApplier, cc_switch_path
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
    path = tmp_path / "bin" / "cc-switch"
    path.parent.mkdir()
    path.write_text("")
    return str(path)


def make(tmp_path, binary, **platform_extra):
    platform = FakeAccountPlatform(root=str(tmp_path / "state"), **platform_extra)
    applier = AiToolsApplier(platform=platform, log=lambda line: None, binary=binary)
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


def test_a_missing_cc_switch_is_bundle_missing_and_runs_nothing(tmp_path):
    applier, platform = make(tmp_path, str(tmp_path / "absent" / "cc-switch"))

    applier.apply(section("ann"), "h1")

    (entry,) = applier.report()["accounts"]
    assert entry == {
        "account": "ann",
        "state": "failed",
        "code": "bundle_missing",
        "params": {"binary": "cc-switch"},
    }
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
    assert {argv[0] for _a, _p, argv in platform.runs} == {binary, "powershell.exe"}
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

    restarted = AiToolsApplier(platform=platform, log=lambda line: None, binary=binary)

    assert restarted.report() == {
        "accounts": [{"account": "ann", "state": "switched", "code": "", "params": {}}]
    }


def test_the_switch_back_before_the_agent_goes_takes_every_account(tmp_path, binary):
    applier, platform = make(
        tmp_path, binary, homes={"ann": "/home/ann", "bob": "/home/bob"}
    )
    applier.apply(section("ann", "bob"), "h1")

    leaving = AiToolsApplier(platform=platform, log=lambda line: None, binary=binary)
    results = leaving.switch_back_all()

    assert [(entry["account"], entry["state"]) for entry in results] == [
        ("ann", "switched_back"),
        ("bob", "switched_back"),
    ]
    assert leaving.switched_accounts() == []


@pytest.mark.parametrize(
    "os_name, path",
    [
        ("linux", "/opt/neutrino/agent/bin/cc-switch"),
        ("darwin", "/Library/Application Support/Neutrino/agent/app/bin/cc-switch"),
        ("windows", "C:\\Program Files\\Neutrino\\agent\\bin\\cc-switch.exe"),
    ],
)
def test_cc_switch_is_the_one_the_agent_s_package_carries(monkeypatch, os_name, path):
    monkeypatch.delenv("ProgramFiles", raising=False)

    assert cc_switch_path(os_name) == path
