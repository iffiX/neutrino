"""public_key: the vectors of RFC 8032, section 7.1."""

import pytest

from neutrino_agent.modules.remote_desktop.rdp.ed25519 import public_key


@pytest.mark.parametrize(
    "seed, public",
    [
        (
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",  # scan: allow
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",  # scan: allow
        ),
        (
            "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",  # scan: allow
            "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",  # scan: allow
        ),
        (
            "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",  # scan: allow
            "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",  # scan: allow
        ),
    ],
)
def test_the_rfc_vectors(seed, public):
    assert public_key(bytes.fromhex(seed)).hex() == public


@pytest.mark.parametrize("length", [0, 31, 33, 64])
def test_a_seed_of_another_length_is_refused(length):
    with pytest.raises(ValueError):
        public_key(bytes(length))
