"""Hermes WebUI's configuration: its two secrets, the login cookie's name and the app's local name."""

from neutrino_agent.modules.hermes_webui.config import HermesWebuiConfig


def test_the_state_s_fields_are_read_and_no_port_among_them():
    config = HermesWebuiConfig.from_dict(
        {
            "secret": "s",
            "password": "p",
            "local_name": "hermes-webui.m.localhost",
            "port": 9100,
        }
    )

    assert (config.secret, config.password, config.local_name) == (
        "s",
        "p",
        "hermes-webui.m.localhost",
    )
    assert not hasattr(config, "port")


def test_the_cookie_name_is_the_hub_s_and_the_webui_s_default_without_one():
    named = HermesWebuiConfig.from_dict({"cookie_name": "hermes_session_a9cae9416662"})

    assert named.cookie_name == "hermes_session_a9cae9416662"
    assert HermesWebuiConfig.from_dict({}).cookie_name == "hermes_session"
    assert HermesWebuiConfig.from_dict({"cookie_name": ""}).cookie_name == (
        "hermes_session"
    )
