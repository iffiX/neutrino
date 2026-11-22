"""AstrBot's configuration: its two secrets, the login cookie's name, the app's local name and the hub's default model, and the cookie's key."""

import hashlib
import hmac

from neutrino_agent.modules.astrbot.config import AstrbotConfig, cookie_key


def test_the_state_s_fields_are_read_and_no_port_among_them():
    config = AstrbotConfig.from_dict(
        {
            "secret": "s",
            "password": "Pass1word",
            "cookie_name": "neutrino_0123456789ab",
            "local_name": "astrbot.m.localhost",
            "model": "qwen2.5:0.5b",
            "port": 9100,
        }
    )

    assert (
        config.secret,
        config.password,
        config.cookie_name,
        config.local_name,
        config.model,
    ) == (
        "s",
        "Pass1word",
        "neutrino_0123456789ab",
        "astrbot.m.localhost",
        "qwen2.5:0.5b",
    )
    assert not hasattr(config, "port")
    assert AstrbotConfig.from_dict({"model": None}).model == ""


def test_the_cookie_s_key_is_derived_from_the_secret_alone():
    expected = hmac.new(b"s", b"neutrino astrbot cookie", hashlib.sha256).digest()

    assert cookie_key("s") == expected
    assert cookie_key("t") != expected
