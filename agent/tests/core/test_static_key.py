"""The agent's static key and its text form."""

from neutrino_agent.core.static_key import make_private_key


def test_a_new_private_key_is_64_lowercase_hex_and_fresh():
    first, second = make_private_key(), make_private_key()

    assert len(first) == 64 and first == first.lower()
    int(first, 16)
    assert first != second
