import pytest

from neutrino_hub.platforms import detect


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", "linux"),
        ("linux2", "linux"),
        ("darwin", "darwin"),
        ("win32", "windows"),
    ],
)
def test_each_system_is_named_by_the_word_the_api_uses(monkeypatch, platform, expected):
    monkeypatch.setattr(detect.sys, "platform", platform)
    assert detect.hub_os() == expected


def test_an_unknown_system_is_refused(monkeypatch):
    monkeypatch.setattr(detect.sys, "platform", "freebsd14")
    with pytest.raises(RuntimeError):
        detect.hub_os()
