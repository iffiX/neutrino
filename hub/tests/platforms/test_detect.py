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


@pytest.mark.parametrize(
    ("platform", "class_name"),
    [
        ("linux", "LinuxHubPlatform"),
        ("darwin", "DarwinHubPlatform"),
        ("win32", "WindowsHubPlatform"),
    ],
)
def test_each_system_has_its_platform_class(monkeypatch, platform, class_name):
    monkeypatch.setattr(detect.sys, "platform", platform)

    assert type(detect.hub_platform()).__name__ == class_name


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_macos_and_windows_hand_out_one_supervised_controller(monkeypatch, platform):
    from neutrino_hub.system.process_control import SupervisedProcessController

    monkeypatch.setattr(detect.sys, "platform", platform)

    controller = detect.process_controller()

    assert isinstance(controller, SupervisedProcessController)
    assert detect.process_controller() is controller
    assert not controller.is_supervising


def test_is_linux_says_which(monkeypatch):
    monkeypatch.setattr(detect.sys, "platform", "linux")
    assert detect.is_linux()
    monkeypatch.setattr(detect.sys, "platform", "darwin")
    assert not detect.is_linux()
