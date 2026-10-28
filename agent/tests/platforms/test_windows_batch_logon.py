"""The batch logon right on Windows, with the logon and the local security policy faked.

What these pin: a standard account is granted ``SeBatchLogonRight`` at its
first task, and the record names the grant as the agent's; an account that
passes a batch logon before, an administrator or one the person granted, is
never granted it and never has it taken away; the right stays while any
task of the account is recorded and goes with the last one, the account
leaving the record; a grant of the agent's is made again at every hold; a
wrong password is ``credential_invalid`` and records nothing; the record
outlives the object, so a new one takes the right away; an account the
machine no longer has leaves the record with no call to the policy; a
policy that refuses is an OSError with its handle closed, and the task stays
recorded for the next release; and the uninstall takes every grant of the
agent's away and deletes the record.
"""

import ctypes
import json

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_batch_logon import WindowsBatchLogonRight

RIGHT = "SeBatchLogonRight"


def win_error(code: int) -> OSError:
    error = OSError(code, f"error {code}")
    error.winerror = code
    return error


class FakeKernel32:
    """GetComputerNameW and CloseHandle."""

    def __init__(self):
        self.closed: list = []

    def GetComputerNameW(self, name, size):
        name.value = "NMXWIN"
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle.value)
        return 1


class FakeMachine:
    """The machine's accounts, their logons and the local security policy.

    An account in ``administrators`` passes a batch logon through its group;
    any other passes once the policy grants its own SID the right.
    """

    def __init__(self, passwords, *, administrators=(), granted=()):
        self.passwords = dict(passwords)
        self.administrators = set(administrators)
        self.rights = {account: {RIGHT} for account in granted}
        self.calls: list = []
        self.error = None
        self.open_status = 0
        self.change_status = 0

    def LookupAccountNameW(self, system, name, sid, sid_size, domain, *sizes):
        account = name.split("\\", 1)[1]
        if account not in self.passwords:
            self.error = win_error(win32.ERROR_NONE_MAPPED)
            return 0
        sid_size._obj.value = 32
        sizes[0]._obj.value = 7
        if sid is None:
            return 0
        sid.value = account.encode()
        sizes[1]._obj.value = win32.SID_TYPE_USER
        return 1

    def LogonUserW(self, account, domain, password, kind, provider, token):
        assert (domain, kind) == (".", win32.LOGON32_LOGON_BATCH)
        self.calls.append(("logon", account))
        if self.passwords.get(account) != password:
            self.error = win_error(win32.ERROR_LOGON_FAILURE)
            return 0
        if account in self.administrators or RIGHT in self.rights.get(account, ()):
            token._obj.value = 0x704
            return 1
        self.error = win_error(win32.ERROR_LOGON_TYPE_NOT_GRANTED)
        return 0

    def LsaOpenPolicy(self, system, attributes, access, handle):
        self.calls.append(("open", access))
        return self.open_status

    def LsaAddAccountRights(self, policy, sid, rights, count):
        account = sid.value.decode()
        self.calls.append(("add", account, _names(rights, count)))
        if self.change_status:
            return self.change_status
        self.rights.setdefault(account, set()).update(_names(rights, count))
        return 0

    def LsaRemoveAccountRights(self, policy, sid, is_all, rights, count):
        account = sid.value.decode()
        self.calls.append(("remove", account, _names(rights, count)))
        assert is_all == 0
        if self.change_status:
            return self.change_status
        held = self.rights.get(account)
        if not held:
            return win32.STATUS_OBJECT_NAME_NOT_FOUND
        held.difference_update(_names(rights, count))
        return 0

    def LsaClose(self, policy):
        self.calls.append(("close",))
        return 0

    def LsaNtStatusToWinError(self, status):
        return 5

    def policy_calls(self) -> list:
        """The calls that changed the policy, in order."""
        return [call for call in self.calls if call[0] in ("add", "remove")]


def _names(rights, count) -> list:
    return [
        ctypes.wstring_at(rights[index].Buffer, rights[index].Length // 2)
        for index in range(count)
    ]


@pytest.fixture
def record_path(tmp_path):
    return str(tmp_path / "state" / "batch_logon.json")


def logon_of(machine, record_path):
    return WindowsBatchLogonRight(
        record_path=record_path, advapi32=machine, kernel32=FakeKernel32()
    )


@pytest.fixture(autouse=True)
def _last_error(monkeypatch):
    holder = {}

    def last_error():
        return holder["machine"].error

    monkeypatch.setattr(win32, "last_error", last_error)
    return holder


def machine_with(holder, *arguments, **keywords) -> FakeMachine:
    machine = FakeMachine(*arguments, **keywords)
    holder["machine"] = machine
    return machine


def read_record(path) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def test_a_standard_account_is_granted_the_right_at_its_first_task(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"ann": "pw"})

    logon_of(machine, record_path).hold("ann", "neutrino_siyuan_ann", "pw")

    assert machine.rights == {"ann": {RIGHT}}
    assert machine.policy_calls() == [("add", "ann", [RIGHT])]
    assert machine.calls[-1] == ("close",)
    assert read_record(record_path) == {
        "accounts": {
            "ann": {
                "account": "ann",
                "is_granted": True,
                "tasks": ["neutrino_siyuan_ann"],
            }
        }
    }


@pytest.mark.parametrize(
    "keywords",
    [{"administrators": ["ann"]}, {"granted": ["ann"]}],
    ids=["administrator", "granted_by_the_person"],
)
def test_an_account_that_passes_a_batch_logon_is_left_alone(
    _last_error, record_path, keywords
):
    machine = machine_with(_last_error, {"ann": "pw"}, **keywords)
    before = {account: set(rights) for account, rights in machine.rights.items()}
    logon = logon_of(machine, record_path)

    logon.hold("ann", "neutrino_siyuan_ann", "pw")
    logon.hold("ann", "neutrino_vscode_ann", "pw")
    is_taken = [
        logon.release("ann", "neutrino_siyuan_ann"),
        logon.release("ann", "neutrino_vscode_ann"),
    ]

    assert is_taken == [False, False]
    assert machine.policy_calls() == []
    assert machine.rights == before
    assert [call for call in machine.calls if call[0] == "logon"] == [("logon", "ann")]
    assert read_record(record_path) == {"accounts": {}}


def test_the_right_stays_while_a_task_is_left_and_goes_with_the_last(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"ann": "pw"})
    logon = logon_of(machine, record_path)
    logon.hold("ann", "neutrino_siyuan_ann", "pw")
    logon.hold("ann", "neutrino_run_as_ann", "pw")

    assert logon.release("ann", "neutrino_run_as_ann") is False
    assert machine.rights == {"ann": {RIGHT}}
    assert read_record(record_path)["accounts"]["ann"]["tasks"] == [
        "neutrino_siyuan_ann"
    ]

    assert logon.release("ann", "neutrino_siyuan_ann") is True
    assert machine.rights == {"ann": set()}
    assert machine.policy_calls()[-1] == ("remove", "ann", [RIGHT])
    assert read_record(record_path) == {"accounts": {}}


def test_the_agent_s_grant_is_made_again_at_every_hold(_last_error, record_path):
    machine = machine_with(_last_error, {"ann": "pw"})
    logon = logon_of(machine, record_path)
    logon.hold("ann", "neutrino_siyuan_ann", "pw")
    machine.rights["ann"].clear()

    logon.hold("ann", "neutrino_siyuan_ann", "pw")

    assert machine.rights == {"ann": {RIGHT}}
    assert [call for call in machine.calls if call[0] == "logon"] == [("logon", "ann")]


def test_an_account_s_name_in_another_case_is_the_same_account(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"Ann": "pw"})
    logon = logon_of(machine, record_path)
    logon.hold("Ann", "neutrino_siyuan_Ann", "pw")
    logon.hold("Ann", "neutrino_run_as_Ann", "pw")

    logon.release("Ann", "neutrino_run_as_Ann")

    assert list(read_record(record_path)["accounts"]) == ["ann"]
    assert machine.rights == {"Ann": {RIGHT}}


def test_a_wrong_password_is_credential_invalid_and_records_nothing(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"ann": "pw"})

    with pytest.raises(ModuleApplyError) as caught:
        logon_of(machine, record_path).hold("ann", "neutrino_siyuan_ann", "old")

    assert (caught.value.code, caught.value.params) == (
        "credential_invalid",
        {"account": "ann"},
    )
    assert machine.policy_calls() == []
    with pytest.raises(FileNotFoundError):
        read_record(record_path)


def test_the_record_outlives_the_object(_last_error, record_path):
    machine = machine_with(_last_error, {"ann": "pw"})
    logon_of(machine, record_path).hold("ann", "neutrino_siyuan_ann", "pw")

    is_taken = logon_of(machine, record_path).release("ann", "neutrino_siyuan_ann")

    assert is_taken is True
    assert machine.rights == {"ann": set()}


def test_an_account_the_machine_no_longer_has_leaves_the_record(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"ann": "pw"})
    logon = logon_of(machine, record_path)
    logon.hold("ann", "neutrino_siyuan_ann", "pw")
    del machine.passwords["ann"]

    assert logon.release("ann", "neutrino_siyuan_ann") is False
    assert machine.policy_calls() == [("add", "ann", [RIGHT])]
    assert read_record(record_path) == {"accounts": {}}


def test_a_policy_that_refuses_keeps_the_task_for_the_next_release(
    _last_error, record_path
):
    machine = machine_with(_last_error, {"ann": "pw"})
    logon = logon_of(machine, record_path)
    logon.hold("ann", "neutrino_siyuan_ann", "pw")
    machine.change_status = 0xC0000022

    with pytest.raises(OSError):
        logon.release("ann", "neutrino_siyuan_ann")

    assert machine.calls[-1] == ("close",)
    assert read_record(record_path)["accounts"]["ann"]["tasks"] == [
        "neutrino_siyuan_ann"
    ]
    machine.change_status = 0
    assert logon.release("ann", "neutrino_siyuan_ann") is True
    assert machine.rights == {"ann": set()}


def test_a_policy_that_will_not_open_is_an_os_error(_last_error, record_path):
    machine = machine_with(_last_error, {"ann": "pw"})
    machine.open_status = 0xC0000022

    with pytest.raises(OSError):
        logon_of(machine, record_path).hold("ann", "neutrino_siyuan_ann", "pw")

    assert machine.policy_calls() == []
    assert ("close",) not in machine.calls


def test_the_uninstall_takes_every_grant_of_the_agent_s_away(_last_error, record_path):
    machine = machine_with(
        _last_error, {"ann": "pw", "bob": "pw", "lab": "pw"}, administrators=["lab"]
    )
    logon = logon_of(machine, record_path)
    for account in ("ann", "bob", "lab"):
        logon.hold(account, f"neutrino_siyuan_{account}", "pw")

    taken = logon.release_all()

    assert sorted(taken) == ["ann", "bob"]
    assert machine.rights == {"ann": set(), "bob": set()}
    with pytest.raises(FileNotFoundError):
        read_record(record_path)
    assert logon.release_all() == []
