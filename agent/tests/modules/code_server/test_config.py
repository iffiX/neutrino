"""The code-server module's configuration.

What these pin: the shape the hub sends parses; every refusal the standard
names comes with the account or the port it is about; and the cookie key
is derived from the instance's secret and from nothing else.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.config import CodeServerConfig, cookie_key

GOOD = {"account": "ann", "port": 8443, "secret": "s"}


def test_the_hub_s_shape_parses():
    config = CodeServerConfig.from_dict({"instances": [GOOD, "junk"]})

    (instance,) = config.instances
    assert (instance.account, instance.port, instance.secret) == ("ann", 8443, "s")
    assert CodeServerConfig.from_dict({}).instances == []


@pytest.mark.parametrize(
    ("instances", "code", "params"),
    [
        ([dict(GOOD, account="a b")], "account_invalid", {"account": "a b"}),
        ([GOOD, dict(GOOD, account="ANN", port=8444)], "account_duplicate", {}),
        ([dict(GOOD, port=80)], "port_invalid", {"port": 80}),
        ([GOOD, dict(GOOD, account="bob")], "port_duplicate", {"port": 8443}),
        ([dict(GOOD, secret="")], "secret_missing", {"account": "ann"}),
    ],
)
def test_each_refusal_names_what_it_is_about(instances, code, params):
    with pytest.raises(ModuleApplyError) as caught:
        CodeServerConfig.from_dict({"instances": instances}).validate()

    assert caught.value.code == code
    for name, value in params.items():
        assert caught.value.params[name] == value


def test_the_cookie_key_follows_the_secret_alone():
    assert cookie_key("s") == cookie_key("s")
    assert cookie_key("s") != cookie_key("t")
    assert len(cookie_key("s")) == 32
