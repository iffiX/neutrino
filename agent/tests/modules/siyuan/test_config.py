"""SiYuan's configuration and the kernel's settings with the module's provider.

What these pin: an instance parses from what the hub sends and checks its
account, its secrets and, on Windows, its password; the provider and model
ids have SiYuan's own form from the SHA-256 of their seeds; the provider is
written after the person's own and replaced whole by its id, taken out with
no key; the agent's and the editor's model point at the first model only
while they name no model the settings hold; the background installer
download is off; and the digest of what was written follows the key, the
address and the models.
"""

import hashlib

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.siyuan.config import (
    SiyuanConfig,
    model_id,
    provider_id,
    settings_digest,
    siyuan_id,
    with_module_settings,
)

KEY = "k" * 32  # scan: allow
URL = "http://127.0.0.1:8317"


def test_an_instance_parses_and_checks_its_account_and_secrets():
    config = SiyuanConfig.from_dict(
        {
            "instances": [
                {"account": "ann", "secret": "s", "access_code": "c", "port": "x"},
                "junk",
            ],
            "gateway_url": URL,
            "models": ["m1", 3, "", "m2"],
        }
    )

    assert [instance.account for instance in config.instances] == ["ann"]
    assert config.instances[0].port == 0
    assert config.gateway_url == URL
    assert config.models == ["m1", "m2"]
    config.validate()


@pytest.mark.parametrize(
    "instances,os_name,code",
    [
        (
            [{"account": "a b", "secret": "s", "access_code": "c"}],
            "linux",
            "account_invalid",
        ),
        (
            [
                {"account": "Ann", "secret": "s", "access_code": "c"},
                {"account": "ann", "secret": "s", "access_code": "c"},
            ],
            "linux",
            "account_duplicate",
        ),
        ([{"account": "ann", "secret": "s"}], "linux", "secret_missing"),
        ([{"account": "ann", "access_code": "c"}], "linux", "secret_missing"),
        (
            [{"account": "ann", "secret": "s", "access_code": "c"}],
            "windows",
            "credential_missing",
        ),
    ],
)
def test_a_configuration_that_does_not_hold_is_refused(instances, os_name, code):
    with pytest.raises(ModuleApplyError) as raised:
        SiyuanConfig.from_dict({"instances": instances}).validate(os_name=os_name)
    assert raised.value.code == code


def test_ids_have_siyuans_own_form_from_their_seeds():
    assert (
        provider_id() == "20000101000000-" + hashlib.sha256(b"neutrino").hexdigest()[:7]
    )
    assert model_id("gpt") == siyuan_id("neutrino/gpt")
    assert model_id("gpt") == (
        "20000101000000-" + hashlib.sha256(b"neutrino/gpt").hexdigest()[:7]
    )


def test_the_provider_follows_the_persons_own_and_the_models_point_at_it():
    own = {"id": "20240101000000-abcdefg", "models": [{"id": "20240101000000-1111111"}]}
    conf = {"ai": {"providers": [own], "agent": {"modelId": ""}}, "system": {}}

    settings = with_module_settings(
        conf, gateway_key=KEY, gateway_url=URL + "/", models=["m1", "m2"]
    )

    providers = settings["ai"]["providers"]
    assert providers[0] == own
    assert providers[1] == {
        "id": provider_id(),
        "enabled": True,
        "apiKey": KEY,
        "baseURL": URL + "/v1",
        "protocol": "openai",
        "requestTimeout": 120,
        "models": [
            {"id": model_id("m1"), "enabled": True, "name": "m1"},
            {"id": model_id("m2"), "enabled": True, "name": "m2"},
        ],
    }
    assert settings["ai"]["agent"]["modelId"] == model_id("m1")
    assert settings["ai"]["editing"]["modelId"] == model_id("m1")
    assert settings["system"]["downloadInstallPkg"] is False
    assert conf["ai"]["providers"] == [own]


def test_a_model_the_settings_hold_stays_chosen_and_the_provider_is_replaced_whole():
    own_model = "20240101000000-1111111"
    conf = {
        "ai": {
            "providers": [
                {"id": "20240101000000-abcdefg", "models": [{"id": own_model}]},
                {"id": provider_id(), "apiKey": "old", "models": []},
            ],
            "agent": {"modelId": own_model},
            "editing": {"modelId": model_id("gone")},
        }
    }

    settings = with_module_settings(
        conf, gateway_key=KEY, gateway_url=URL, models=["m1"]
    )

    ids = [provider["id"] for provider in settings["ai"]["providers"]]
    assert ids == ["20240101000000-abcdefg", provider_id()]
    assert settings["ai"]["providers"][1]["apiKey"] == KEY
    assert settings["ai"]["agent"]["modelId"] == own_model
    assert settings["ai"]["editing"]["modelId"] == model_id("m1")


def test_no_key_takes_the_provider_out_and_still_turns_the_download_off():
    conf = {"ai": {"providers": [{"id": provider_id()}]}, "system": {"x": 1}}

    settings = with_module_settings(conf, gateway_key="", gateway_url=URL, models=["m"])

    assert settings["ai"]["providers"] == []
    assert settings["system"] == {"x": 1, "downloadInstallPkg": False}


def test_the_digest_follows_the_key_the_address_and_the_models():
    first = settings_digest(KEY, URL, ["m1"])

    assert first == settings_digest(KEY, URL, ["m1"])
    assert first != settings_digest("other", URL, ["m1"])
    assert first != settings_digest(KEY, "http://127.0.0.1:9000", ["m1"])
    assert first != settings_digest(KEY, URL, ["m1", "m2"])
