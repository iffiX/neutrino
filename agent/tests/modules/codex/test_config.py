"""The Codex module's configuration: the enabled accounts, each with its login on Windows."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codex.config import CodexConfig


def test_the_accounts_parse_in_their_order_with_their_logins():
    parsed = CodexConfig.from_dict(
        {"accounts": [{"account": "ann", "password": "pw"}, {"account": "bob"}]}
    )

    assert isinstance(parsed, CodexConfig)
    assert [(item.account, item.password) for item in parsed.accounts] == [
        ("ann", "pw"),
        ("bob", ""),
    ]
    parsed.validate()


def test_windows_refuses_an_account_with_no_login():
    with pytest.raises(ModuleApplyError) as refused:
        CodexConfig.from_dict({"accounts": [{"account": "bob"}]}).validate(
            os_name="windows"
        )
    assert (refused.value.code, refused.value.params) == (
        "credential_missing",
        {"account": "bob"},
    )
