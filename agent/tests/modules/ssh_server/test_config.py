"""The SSH server module's configuration.

What these pin: each instance is read with its account, key, shell and
password, anything not a dict left out; an apply refuses an account name a
unit or a task cannot carry, the same account twice in any case, a key that
is empty or not an OpenSSH public key, and on Windows an instance with no
password, each naming the account.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.ssh_server.config import (
    SshServerConfig,
    SshServerInstance,
)

from tests.modules.ssh_server.conftest import PUBLIC_KEY


def instance(account="lab", key=PUBLIC_KEY, **extra):
    return {"account": account, "authorized_key": key, **extra}


def test_an_instance_is_read_whole():
    parsed = SshServerConfig.from_dict(
        {
            "instances": [
                instance(shell_path=" /bin/zsh ", password="pw"),  # scan: allow
                "not an instance",
            ]
        }
    )

    assert parsed.instances == [
        SshServerInstance(
            account="lab",
            authorized_key=PUBLIC_KEY,
            shell_path="/bin/zsh",
            password="pw",  # scan: allow
        )
    ]


def test_a_missing_list_is_no_instance():
    assert SshServerConfig.from_dict({}).instances == []
    assert SshServerConfig.from_dict({"instances": "lab"}).instances == []


def test_a_record_carries_its_port():
    assert (
        SshServerInstance.from_dict({"account": "lab", "port": "22001"}).port == 22001
    )
    assert SshServerInstance.from_dict({"account": "lab", "port": "x"}).port == 0


@pytest.mark.parametrize(
    "instances, code, account",
    [
        ([instance(account="")], "account_invalid", ""),
        ([instance(account="lab user")], "account_invalid", "lab user"),
        ([instance(account="-lab")], "account_invalid", "-lab"),
        ([instance(), instance(account="LAB")], "account_duplicate", "LAB"),
        ([instance(key="")], "key_missing", "lab"),
        ([instance(key="ssh-ed25519 garbage")], "key_missing", "lab"),
    ],
    ids=[
        "an empty account",
        "a space",
        "a leading dash",
        "twice in another case",
        "no key",
        "not a key",
    ],
)
def test_an_apply_refuses_naming_the_account(instances, code, account):
    with pytest.raises(ModuleApplyError) as refusal:
        SshServerConfig.from_dict({"instances": instances}).validate()

    assert (refusal.value.code, refusal.value.params) == (code, {"account": account})


def test_windows_needs_each_account_s_password():
    parsed = SshServerConfig.from_dict({"instances": [instance()]})
    parsed.validate(os_name="linux")

    with pytest.raises(ModuleApplyError) as refusal:
        parsed.validate(os_name="windows")

    assert refusal.value.code == "credential_missing"
    assert refusal.value.params == {"account": "lab"}
