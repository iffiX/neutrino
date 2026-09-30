"""The address sampler: the runtime converges only when the set moved.

The first sample is not itself news, a set equal to the last says nothing,
and a set that moved runs the converge step once, which hands both roles
their state. A sample whose overlay devices moved has converged already.
"""

from neutrino_hub.web import address_sampler as sampler_module
from neutrino_hub.web.address_sampler import PanelAddressSampler


class StubRuntime:
    """Only what the sampler reaches for."""

    def __init__(self):
        self.urls = ["https://192.168.100.1:8443"]
        self.calls: list = []
        self.is_device_moved = False

    def follow_overlay_devices(self) -> bool:
        self.calls.append("follow")
        return self.is_device_moved

    def converge_network_blocking(self, only=None) -> str:
        self.calls.append("converge")
        return "applied"


def sampler(monkeypatch) -> tuple:
    runtime = StubRuntime()
    monkeypatch.setattr(sampler_module, "channel_urls", lambda given: list(given.urls))
    return PanelAddressSampler(runtime=runtime), runtime


def test_the_first_sample_is_not_itself_news(monkeypatch):
    watcher, runtime = sampler(monkeypatch)

    assert watcher.sample_once() is False
    assert "converge" not in runtime.calls


def test_a_set_that_did_not_move_converges_nothing(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()

    assert watcher.sample_once() is False
    assert "converge" not in runtime.calls


def test_a_set_that_moved_converges_once(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()

    runtime.urls = ["https://192.168.100.1:8443", "https://100.64.0.1:8443"]

    assert watcher.sample_once() is True
    assert runtime.calls.count("converge") == 1
    assert watcher.sample_once() is False
    assert runtime.calls.count("converge") == 1


def test_a_device_that_moved_is_not_converged_on_twice(monkeypatch):
    watcher, runtime = sampler(monkeypatch)
    watcher.sample_once()
    runtime.is_device_moved = True

    runtime.urls = ["https://192.168.100.1:8443", "https://10.126.126.1:8443"]

    assert watcher.sample_once() is True
    assert "converge" not in runtime.calls


def test_each_sample_follows_the_overlay_devices_before_reading(monkeypatch):
    """A console bringing its network up moves the firewall first, so the set
    read after it names the overlay's address."""
    watcher, runtime = sampler(monkeypatch)
    monkeypatch.setattr(
        sampler_module,
        "channel_urls",
        lambda given: given.calls.append("urls") or list(given.urls),
    )

    watcher.sample_once()

    assert runtime.calls == ["follow", "urls"]
