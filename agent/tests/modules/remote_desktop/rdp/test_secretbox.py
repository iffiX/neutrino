"""NaCl's secretbox open against a vector libsodium made.

The vector is ``crypto_secretbox_easy`` of ``OPEN SESAME, from libsodium``
under the key ``00 01 .. 1f`` and the nonce ``01 02 .. 18``: the tag, then
the ciphertext.
"""

import pytest

from neutrino_agent.modules.remote_desktop.rdp.secretbox import secretbox_open

KEY = bytes(range(32))
NONCE = bytes(range(1, 25))
MESSAGE = b"OPEN SESAME, from libsodium"
SEALED = bytes.fromhex(
    "4b9636d55b8621d84fda89e6c7e7d608447cd366200e6229440ab0f3819d9dfa"  # scan: allow
    "5f2913a13be433cd9bd15a"  # scan: allow
)


def test_what_libsodium_sealed_opens():
    assert secretbox_open(SEALED, NONCE, KEY) == MESSAGE


def test_a_changed_byte_does_not_open():
    changed = SEALED[:-1] + bytes([SEALED[-1] ^ 1])

    with pytest.raises(ValueError):
        secretbox_open(changed, NONCE, KEY)


def test_another_key_does_not_open():
    with pytest.raises(ValueError):
        secretbox_open(SEALED, NONCE, bytes(32))


@pytest.mark.parametrize(
    "sealed, nonce, key",
    [
        (SEALED, NONCE, KEY[:31]),
        (SEALED, NONCE[:23], KEY),
        (SEALED[:15], NONCE, KEY),
    ],
)
def test_a_wrong_size_is_refused(sealed, nonce, key):
    with pytest.raises(ValueError):
        secretbox_open(sealed, nonce, key)
