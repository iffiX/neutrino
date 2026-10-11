"""The Codeg module's configuration.

What these pin: the shape the hub sends parses, the password included; every
refusal the standard names comes with the account or the port it is about,
``credential_missing`` on Windows alone; the instance token is derived from
the instance's secret and from nothing else, as unpadded base64url; and
the subprotocol is the token's bytes as unpadded base64url behind
``codeg-token.``.
"""

import base64
import hashlib
import hmac

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codeg.config import (
    CodegConfig,
    instance_token,
    subprotocol_of,
)

GOOD = {"account": "ann", "port": 3101, "secret": "s"}


def test_the_hub_s_shape_parses():
    config = CodegConfig.from_dict(
        {"instances": [dict(GOOD, password="login-pw"), "junk"]}
    )

    (instance,) = config.instances
    assert (instance.account, instance.port, instance.secret, instance.password) == (
        "ann",
        3101,
        "s",
        "login-pw",
    )
    assert CodegConfig.from_dict({}).instances == []
    assert (
        CodegConfig.from_dict({"instances": [dict(GOOD, port="x")]}).instances[0].port
        == 0
    )


@pytest.mark.parametrize(
    ("instances", "code", "params"),
    [
        ([dict(GOOD, account="a b")], "account_invalid", {"account": "a b"}),
        ([GOOD, dict(GOOD, account="ANN", port=3102)], "account_duplicate", {}),
        ([dict(GOOD, port=80)], "port_invalid", {"port": 80}),
        ([GOOD, dict(GOOD, account="bob")], "port_duplicate", {"port": 3101}),
        ([dict(GOOD, secret="")], "secret_missing", {"account": "ann"}),
    ],
)
def test_each_refusal_names_what_it_is_about(instances, code, params):
    with pytest.raises(ModuleApplyError) as caught:
        CodegConfig.from_dict({"instances": instances}).validate()

    assert caught.value.code == code
    for name, value in params.items():
        assert caught.value.params[name] == value


def test_a_windows_instance_needs_its_accounts_password():
    config = CodegConfig.from_dict({"instances": [GOOD]})

    config.validate(os_name="linux")
    config.validate(os_name="darwin")
    with pytest.raises(ModuleApplyError) as caught:
        config.validate(os_name="windows")

    assert caught.value.code == "credential_missing"
    assert caught.value.params == {"account": "ann"}
    CodegConfig.from_dict({"instances": [dict(GOOD, password="pw")]}).validate(
        os_name="windows"
    )


def test_the_instance_token_follows_the_secret_alone():
    expected = hmac.new(b"s", b"neutrino codeg token", hashlib.sha256).digest()

    assert instance_token("s") == instance_token("s")
    assert instance_token("s") != instance_token("t")
    assert instance_token("s") == (
        base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
    )
    assert len(instance_token("s")) == 43
    assert "=" not in instance_token("s")


def test_the_subprotocol_carries_the_token_as_unpadded_base64url():
    token = instance_token("s")

    protocol = subprotocol_of(token)

    assert protocol.startswith("codeg-token.")
    encoded = protocol[len("codeg-token.") :]
    assert "=" not in encoded
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == (
        token.encode()
    )
