"""The agent's static key: RFC 7748's X25519 and the key's text form."""

import pytest

from neutrino_agent.core.static_key import make_private_key, public_key_of, x25519


def test_x25519_matches_the_rfcs_first_vector():
    scalar = bytes.fromhex(
        "a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"
    )
    u = bytes.fromhex(
        "e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c"
    )

    assert x25519(scalar, u).hex() == (
        "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
    )


def test_x25519_matches_the_rfcs_second_vector():
    scalar = bytes.fromhex(
        "4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d"
    )
    u = bytes.fromhex(
        "e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a493"
    )

    assert x25519(scalar, u).hex() == (
        "95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957"
    )


def test_the_public_keys_of_the_rfcs_alice_and_bob():
    alice = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    bob = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"

    assert public_key_of(alice) == (
        "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
    )
    assert public_key_of(bob) == (
        "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
    )


def test_both_sides_reach_the_rfcs_shared_secret():
    alice = bytes.fromhex(
        "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
    )
    bob_public = bytes.fromhex(
        "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
    )

    assert x25519(alice, bob_public).hex() == (
        "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    )


def test_a_new_private_key_is_64_lowercase_hex_and_fresh():
    first, second = make_private_key(), make_private_key()

    assert len(first) == 64 and first == first.lower()
    int(first, 16)
    assert first != second


@pytest.mark.parametrize("key", ["", "ab" * 31, "zz" * 32, "ab" * 33])
def test_a_key_that_is_not_64_hex_is_refused(key):
    with pytest.raises(ValueError):
        public_key_of(key)
