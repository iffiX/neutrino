"""Reading the gateway's model catalog on the panel's thread.

What these pin: a read that changed the stored read says so and one that did
not stays quiet; a box with no management key asks nothing; and the loop
reading again soon while no read succeeded since the start, then at its
interval or at a wake.
"""

import threading

from neutrino_hub.web import model_catalog_sampler as sampler_module
from neutrino_hub.web.model_catalog_sampler import PanelModelCatalogSampler


class Reads:
    """The catalog reader, answering each read in turn and counting them."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.count = 0
        self.done = threading.Event()

    def __call__(self, *, port, management_key):
        del port, management_key
        self.count += 1
        answer = self.answers.pop(0) if self.answers else False
        if not self.answers:
            self.done.set()
        return answer


def keyed(monkeypatch, key="k"):
    monkeypatch.setattr(sampler_module, "read_management_key", lambda: key)
    monkeypatch.setattr(
        sampler_module,
        "load_config",
        lambda: type("Config", (), {"listen_port": 8317})(),
    )


def test_a_read_that_changed_the_stored_read_says_so(monkeypatch):
    keyed(monkeypatch)
    changes = []
    reads = Reads([True, False, None])
    sampler = PanelModelCatalogSampler(
        on_change=lambda: changes.append(1), refresh=reads
    )

    assert sampler.read_once() is True
    assert sampler.read_once() is False
    assert sampler.read_once() is None
    assert changes == [1]


def test_a_box_with_no_management_key_asks_nothing(monkeypatch):
    keyed(monkeypatch, key="")
    reads = Reads([True])
    sampler = PanelModelCatalogSampler(on_change=lambda: None, refresh=reads)

    assert sampler.read_once() is None
    assert reads.count == 0


def test_the_loop_reads_again_soon_until_a_read_succeeds_then_at_a_wake(monkeypatch):
    keyed(monkeypatch)
    reads = Reads([None, None, False])
    sampler = PanelModelCatalogSampler(
        on_change=lambda: None, interval_s=3600, retry_s=0.05, refresh=reads
    )
    sampler.start()
    try:
        assert reads.done.wait(5)
        assert reads.count == 3
        reads.answers = [True]
        reads.done.clear()
        sampler.wake()
        assert reads.done.wait(5)
        assert reads.count == 4
    finally:
        sampler.stop()
