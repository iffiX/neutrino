"""The desktop shares managed machines declare.

A share is only ever as true as the last beat that said so: it is recorded
when a machine declares it, gone when the machine stops, and gone again when
the machine goes quiet — no timer, no reconcile, and nothing on disk.
"""

from neutrino_hub.modules.services.device_shares import DeviceShareRegistry

MAC = "aa:bb:cc:dd:ee:ff"
OTHER = "11:22:33:44:55:66"


def declared(registry, mac=MAC, share_id="s1", host="192.168.100.5", now=0.0):
    registry.declare(
        mac_address=mac,
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
    assert live[0].mac_address == MAC


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

    registry.withdraw(MAC)

    assert registry.live(now=0.0) == []


def test_a_machine_that_goes_quiet_ages_out_of_the_list():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry, now=0.0)

    assert len(registry.live(now=29.0)) == 1
    assert registry.live(now=31.0) == []


def test_a_declaration_missing_its_address_or_id_is_not_recorded():
    registry = DeviceShareRegistry(window_s=30)

    declared(registry, share_id="", now=0.0)
    declared(registry, mac=OTHER, host="", now=0.0)
    registry.declare(
        mac_address="", share_id="s3", hostname="x", host="1.2.3.4", port=1, now=0.0
    )

    assert registry.live(now=0.0) == []


def test_the_fingerprint_moves_when_the_live_set_does():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry, now=0.0)
    first = registry.fingerprint(now=0.0)

    declared(registry, mac=OTHER, share_id="s2", host="192.168.100.7", now=0.0)

    assert registry.fingerprint(now=0.0) != first
    # And moves back when a share ages out, so a stale list recomposes.
    assert registry.fingerprint(now=99.0) == ()


def test_the_machines_are_addressed_case_insensitively():
    registry = DeviceShareRegistry(window_s=30)
    declared(registry, mac=MAC.upper(), now=0.0)

    registry.withdraw(MAC.lower())

    assert registry.live(now=0.0) == []
