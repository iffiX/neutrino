"""The desktop shares managed machines declare.

A share is only ever as true as the last beat that said so: it is recorded
against the device's id when a machine declares it, gone when the machine
stops, and gone again when the machine goes quiet. No timer, no reconcile,
and nothing on disk.
"""

from neutrino_hub.modules.services.device_shares import DeviceShareRegistry

DEVICE = "device-one"
OTHER = "device-two"


def declared(registry, device=DEVICE, share_id="s1", host="192.168.100.5", now=0.0):
    registry.declare(
        device_id=device,
        share_id=share_id,
        hostname="workshop",
        host=host,
        port=21118,
        now=now,
    )


def test_a_declared_share_is_live_with_what_the_machine_said():
    registry = DeviceShareRegistry(window_s=30)

    declared(registry)

    live = registry.live(now=0.0)
    assert [share.share_id for share in live] == ["s1"]
    assert live[0].host == "192.168.100.5"
    assert live[0].port == 21118
    assert live[0].device_id == DEVICE


def test_a_share_carries_whose_desktop_it_is_and_how_many_watch():
    registry = DeviceShareRegistry(window_s=30)

    registry.declare(
        device_id=DEVICE,
        share_id="s1",
        hostname="workshop",
        host="192.168.100.5",
        port=21118,
        account="pat",
        connected_count=3,
        now=0.0,
    )

    (share,) = registry.live(now=0.0)
    assert share.account == "pat"
    assert share.connected_count == 3


def test_a_share_naming_neither_carries_an_empty_account_and_no_viewers():
    registry = DeviceShareRegistry(window_s=30)

    declared(registry)

    (share,) = registry.live(now=0.0)
    assert share.account == ""
    assert share.connected_count == 0


def test_declaring_again_replaces_the_machines_one_share():
    registry = DeviceShareRegistry(window_s=30)

    declared(registry, share_id="s1", now=0.0)
    declared(registry, share_id="s2", host="192.168.100.9", now=1.0)

    live = registry.live(now=1.0)
    assert [share.share_id for share in live] == ["s2"]
    assert live[0].host == "192.168.100.9"


def test_a_machine_that_stops_sharing_is_withdrawn_at_once():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry)

    registry.withdraw(DEVICE)

    assert registry.live(now=0.0) == []


def test_a_machine_that_goes_quiet_ages_out_of_the_list():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry, now=0.0)

    assert len(registry.live(now=29.0)) == 1
    assert registry.live(now=31.0) == []


def test_a_declaration_missing_its_address_or_id_is_not_recorded():
    registry = DeviceShareRegistry(window_s=30)

    declared(registry, share_id="", now=0.0)
    declared(registry, device=OTHER, host="", now=0.0)
    registry.declare(
        device_id="", share_id="s3", hostname="x", host="1.2.3.4", port=1, now=0.0
    )

    assert registry.live(now=0.0) == []


def test_the_fingerprint_moves_when_the_live_set_does():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry, now=0.0)
    first = registry.fingerprint(now=0.0)

    declared(registry, device=OTHER, share_id="s2", host="192.168.100.7", now=0.0)

    assert registry.fingerprint(now=0.0) != first
    # And moves back when a share ages out, so a stale list recomposes.
    assert registry.fingerprint(now=99.0) == ()
