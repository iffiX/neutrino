"""``nclient settings``: show and set, one name per control of the Settings page."""

import pytest

from neutrino_client.cli import settings, wording


def test_show_prints_each_setting_its_value_and_its_values(running, capsys):
    running.state["is_ssh_include_enabled"] = True

    assert settings.main_show() == 0

    assert capsys.readouterr().out.splitlines() == [
        "language     en  en, zh-CN",
        "theme        dark  system, dark, light",
        "ssh_include  on  on, off",
    ]


@pytest.mark.parametrize(
    "name, value, body",
    [
        ("language", "zh-CN", {"language": "zh-CN"}),
        ("theme", "light", {"theme": "light"}),
        ("ssh_include", "on", {"is_ssh_include_enabled": True}),
        ("ssh_include", "off", {"is_ssh_include_enabled": False}),
    ],
)
def test_set_sends_the_one_setting(running, name, value, body):
    assert settings.main_set(name, value) == 0
    assert running.posts("/api/settings/set") == [body]


def test_a_value_the_setting_does_not_take_exits_1(running, capsys):
    assert settings.main_set("theme", "pink") == 1

    assert running.posts("/api/settings/set") == []
    assert capsys.readouterr().err.strip() == wording.word_code(
        "setting_value_unknown", {"name": "theme", "value": "pink"}
    )


def test_a_name_that_is_no_setting_prints_the_names(running, capsys):
    assert settings.main_set("font", "12") == 1
    assert capsys.readouterr().err.strip() == (
        "no setting named font; there are: language, theme, ssh_include"
    )


def test_no_running_client_is_client_not_running(running, capsys):
    running.is_running = False

    assert settings.main_show() == 1
    assert settings.main_set("theme", "dark") == 1
    assert capsys.readouterr().err.count(wording.word_code("client_not_running")) == 2
