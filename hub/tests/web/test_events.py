"""The panel event bus: who hears what, and what it drops.

An event is a hint rather than a value, so the bus is judged on five things:
a publish from a worker thread reaching a subscriber on the loop, identical
hints inside the window arriving once, a reading never being coalesced away,
a subscriber too far behind losing the oldest rather than the newest, and
unsubscribing being final.
"""

import asyncio
import threading

from neutrino_hub.web.constants import (
    WEB_EVENT_CONFIG,
    WEB_EVENT_DEVICES,
    WEB_EVENT_METRICS,
    WEB_EVENT_MODULE_ORDER,
)
from neutrino_hub.web.events import PanelEventBus


def on_loop(body) -> None:
    """Run one coroutine function on its own loop, as the panel serves on.

    Args:
        body: The test's async body, taking nothing.
    """
    asyncio.run(body())


async def settled(queue: asyncio.Queue) -> list:
    """Every event delivered so far, without waiting for another."""
    await asyncio.sleep(0)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_a_publish_from_a_thread_reaches_a_subscriber():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()

        thread = threading.Thread(
            target=bus.publish, args=(WEB_EVENT_CONFIG, "router/network.json")
        )
        thread.start()
        thread.join()

        event = await asyncio.wait_for(queue.get(), 2.0)
        assert event["type"] == WEB_EVENT_CONFIG
        assert event["key"] == "router/network.json"
        assert event["at"]

    on_loop(body)


def test_every_subscriber_hears_the_same_event():
    async def body():
        bus = PanelEventBus()
        first = bus.subscribe()
        second = bus.subscribe()

        bus.publish(WEB_EVENT_DEVICES)

        assert [event["type"] for event in await settled(first)] == [WEB_EVENT_DEVICES]
        assert [event["type"] for event in await settled(second)] == [WEB_EVENT_DEVICES]

    on_loop(body)


def test_identical_events_inside_the_window_arrive_once():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()

        for _ in range(5):
            bus.publish(WEB_EVENT_MODULE_ORDER, "aa:bb:cc:dd:ee:ff")

        assert len(await settled(queue)) == 1

    on_loop(body)


def test_an_event_carrying_a_reading_is_never_coalesced():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()

        bus.publish(WEB_EVENT_METRICS, "aa:bb", data={"cpu_percent": 4.0})
        bus.publish(WEB_EVENT_METRICS, "aa:bb", data={"cpu_percent": 91.0})

        assert [event["data"] for event in await settled(queue)] == [
            {"cpu_percent": 4.0},
            {"cpu_percent": 91.0},
        ]

    on_loop(body)


def test_an_event_carrying_nothing_has_no_data_field():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()

        bus.publish(WEB_EVENT_DEVICES)

        assert "data" not in (await settled(queue))[0]

    on_loop(body)


def test_another_key_of_the_same_type_is_its_own_event():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()

        bus.publish(WEB_EVENT_MODULE_ORDER, "aa:bb:cc:dd:ee:ff")
        bus.publish(WEB_EVENT_MODULE_ORDER, "aa:bb:cc:dd:ee:00")

        assert [event["key"] for event in await settled(queue)] == [
            "aa:bb:cc:dd:ee:ff",
            "aa:bb:cc:dd:ee:00",
        ]

    on_loop(body)


def test_a_subscriber_that_falls_behind_loses_the_oldest():
    async def body():
        bus = PanelEventBus(queue_limit=3)
        queue = bus.subscribe()

        for index in range(5):
            bus.publish(WEB_EVENT_CONFIG, f"devices/{index}.json")

        assert [event["key"] for event in await settled(queue)] == [
            "devices/2.json",
            "devices/3.json",
            "devices/4.json",
        ]

    on_loop(body)


def test_unsubscribing_stops_delivery():
    async def body():
        bus = PanelEventBus()
        queue = bus.subscribe()
        bus.unsubscribe(queue)

        bus.publish(WEB_EVENT_DEVICES)

        assert await settled(queue) == []

    on_loop(body)
