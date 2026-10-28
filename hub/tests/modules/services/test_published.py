"""The published list a read gets after an expiry: a compose begun before the
expiry replaces no list composed after it."""

import threading

from neutrino_hub.modules.services.published import PublishedServiceCache


def test_a_compose_begun_before_an_expiry_replaces_no_later_list():
    cache = PublishedServiceCache(
        declared_probe=None, served_models=None, units=None, desired_states=object()
    )
    started = threading.Event()
    release = threading.Event()
    composed = []

    def compose():
        composed.append(len(composed))
        if len(composed) == 1:
            started.set()
            release.wait(5)
            return [{"id": "before"}], []
        return [{"id": "after"}], []

    cache._compose = compose
    early = threading.Thread(target=cache.refresh)
    early.start()
    assert started.wait(5)

    cache.expire()
    first, _ = cache.entries()
    release.set()
    early.join(5)
    second, _ = cache.entries()

    assert first == [{"id": "after"}]
    assert second == [{"id": "after"}]
    assert len(composed) == 2


def test_a_compose_finished_before_an_expiry_is_read_again_after_it():
    cache = PublishedServiceCache(
        declared_probe=None, served_models=None, units=None, desired_states=object()
    )
    lists = iter([[{"id": "before"}], [{"id": "after"}]])

    def compose():
        return next(lists), []

    cache._compose = compose

    cache.refresh()
    cache.expire()

    assert cache.entries()[0] == [{"id": "after"}]
