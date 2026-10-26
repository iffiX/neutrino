"""The Codeg module's configuration.

What these pin: the shape the hub sends parses, the password included; every
refusal the standard names comes with the account or the port it is about,
``credential_missing`` on Windows alone; the instance token is derived from
the instance's secret and from nothing else, as unpadded base64url; the
subprotocol is the token's bytes as unpadded base64url behind
``codeg-token.``; and the cookie key is derived from the secret with a
label of its own.
"""

import base64
import hashlib
import hmac

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codeg.config import (
    CodegConfig,
    cookie_key,
    instance_token,
    subprotocol_of,
)

GOOD = {
    "account": "ann",
    "secret": "s",
    "local_name": "codeg-ann.m.localhost",
    "cookie_name": "neutrino_0123456789ab",
}


def test_the_hub_s_shape_parses_with_no_port():
    config = CodegConfig.from_dict(
        {"instances": [dict(GOOD, password="login-pw"), "junk"]}
    )

    (instance,) = config.instances
    assert (instance.account, instance.port, instance.secret, instance.password) == (
        "ann",
        0,
        "s",
        "login-pw",
    )
    assert instance.local_name == "codeg-ann.m.localhost"
    assert instance.cookie_name == "neutrino_0123456789ab"
    assert CodegConfig.from_dict({}).instances == []


@pytest.mark.parametrize(
    ("instances", "code", "params"),
    [
        ([dict(GOOD, account="a b")], "account_invalid", {"account": "a b"}),
        ([GOOD, dict(GOOD, account="ANN")], "account_duplicate", {}),
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


def test_the_cookie_key_follows_the_secret_alone_with_its_own_label():
    expected = hmac.new(b"s", b"neutrino codeg cookie", hashlib.sha256).digest()

    assert cookie_key("s") == cookie_key("s") == expected
    assert cookie_key("s") != cookie_key("t")
    assert (
        cookie_key("s")
        != hmac.new(b"s", b"neutrino codeg token", hashlib.sha256).digest()
    )
    assert len(cookie_key("s")) == 32


def test_the_subprotocol_carries_the_token_as_unpadded_base64url():
    token = instance_token("s")

    protocol = subprotocol_of(token)

    assert protocol.startswith("codeg-token.")
    encoded = protocol[len("codeg-token.") :]
    assert "=" not in encoded
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == (
        token.encode()
    )
