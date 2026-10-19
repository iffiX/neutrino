"""NaCl's crypto_box against published and libsodium-made vectors.

The key pair is RFC 7748's Alice and Bob; their box key is the ``firstkey``
of NaCl's own ``tests/box.c``. The sealed vector was made with libsodium's
``crypto_box_easy`` from Alice's secret key, Bob's public key and NaCl's
test nonce, laid out as Go's ``box.Seal`` lays it out: nonce, tag,
ciphertext.
"""

import pytest

from neutrino_hub.modules.frp.nacl_box import (
    box_key,
    box_open,
    box_seal,
    hsalsa20,
)

ALICE_SECRET = bytes.fromhex(
    "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
)
ALICE_PUBLIC = bytes.fromhex(
    "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
)
BOB_SECRET = bytes.fromhex(
    "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"
)
BOB_PUBLIC = bytes.fromhex(
    "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
)
FIRSTKEY = bytes.fromhex(
    "1b27556473e985d462cd51197a9a46c76009549eac6474f206c4ee0844f68389"
)
NONCE = bytes.fromhex("69696ee955b62b73cd62bda875fc73d68219e0036b7a0b37")
MESSAGE = b"OPENFRPeyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.example"  # scan: allow
SEALED = bytes.fromhex(
    "69696ee955b62b73cd62bda875fc73d68219e0036b7a0b37b71c3934008db7c822c0bf9bd7"
    "ba828b7fce211432bbb0c374c873c9815613fa7351a0db6b7e343c4f43543c12e63ed94c79"
    "3286d134e52c3e2ae1ebd75cc9366d629b"
)


def test_the_box_key_is_the_firstkey_of_nacls_tests():
    assert box_key(peer_public=BOB_PUBLIC, own_private=ALICE_SECRET) == FIRSTKEY
    assert box_key(peer_public=ALICE_PUBLIC, own_private=BOB_SECRET) == FIRSTKEY


def test_hsalsa20_of_zeros_under_the_shared_secret_is_the_box_key():
    shared = bytes.fromhex(
        "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    )

    assert hsalsa20(shared, bytes(16)) == FIRSTKEY


def test_sealing_gives_libsodiums_bytes():
    assert (
        box_seal(MESSAGE, NONCE, peer_public=BOB_PUBLIC, own_private=ALICE_SECRET)
        == SEALED
    )


def test_the_recipient_opens_it():
    assert box_open(SEALED, peer_public=ALICE_PUBLIC, own_private=BOB_SECRET) == (
        MESSAGE
    )


@pytest.mark.parametrize("length", [0, 1, 63, 64, 65, 200])
def test_every_length_goes_round(length):
    message = bytes(range(256))[:length]

    sealed = box_seal(message, NONCE, peer_public=BOB_PUBLIC, own_private=ALICE_SECRET)

    assert len(sealed) == 24 + 16 + length
    assert box_open(sealed, peer_public=ALICE_PUBLIC, own_private=BOB_SECRET) == (
        message
    )


def test_a_changed_byte_is_refused():
    tampered = SEALED[:-1] + bytes([SEALED[-1] ^ 1])

    with pytest.raises(ValueError):
        box_open(tampered, peer_public=ALICE_PUBLIC, own_private=BOB_SECRET)


def test_text_shorter_than_a_nonce_and_a_tag_is_refused():
    with pytest.raises(ValueError):
        box_open(SEALED[:39], peer_public=ALICE_PUBLIC, own_private=BOB_SECRET)
