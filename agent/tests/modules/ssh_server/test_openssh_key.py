"""OpenSSH key forms, read without a crypto library.

What these pin: a public key line is a type and a base64 blob of that same
type, a comment allowed; anything else is not a key; the fingerprint is
OpenSSH's own, checked against what ``ssh-keygen -l`` printed for the same
key; and the public half is read from an unencrypted OpenSSH private key
file, a file of any other form refused.
"""

import base64

import pytest

from neutrino_agent.modules.ssh_server.openssh_key import (
    fingerprint,
    is_public_key,
    public_key_blob,
    public_line_of_private,
)

from tests.modules.ssh_server.conftest import (
    PUBLIC_KEY,
    PUBLIC_KEY_FINGERPRINT,
    private_key_text,
)


@pytest.mark.parametrize(
    "line",
    [PUBLIC_KEY, PUBLIC_KEY + " lab@machine", "  " + PUBLIC_KEY + "\n"],
    ids=["bare", "with a comment", "with spaces around"],
)
def test_a_public_key_line_is_read(line):
    assert is_public_key(line)
    assert public_key_blob(line) == base64.b64decode(PUBLIC_KEY.split()[1])


@pytest.mark.parametrize(
    "line",
    [
        "",
        "ssh-ed25519",
        "ssh-ed25519 not*base64",
        "ssh-rsa " + PUBLIC_KEY.split()[1],
        "ssh-ed25519 AAAA",
    ],
    ids=["empty", "a type alone", "not base64", "another type", "a short blob"],
)
def test_anything_else_is_not_a_key(line):
    assert not is_public_key(line)
    with pytest.raises(ValueError):
        public_key_blob(line)


def test_the_fingerprint_is_openssh_s():
    assert fingerprint(PUBLIC_KEY + " comment") == PUBLIC_KEY_FINGERPRINT


def test_the_public_half_is_read_from_a_private_key_file():
    assert public_line_of_private(private_key_text(PUBLIC_KEY)) == PUBLIC_KEY


@pytest.mark.parametrize(
    "text",
    [
        "",
        "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----\n",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nbm90IGEga2V5\n-----END OPENSSH PRIVATE KEY-----\n",
        private_key_text(PUBLIC_KEY)[:120] + "\n-----END OPENSSH PRIVATE KEY-----\n",
    ],
    ids=["empty", "another form", "not a key", "cut short"],
)
def test_a_file_that_is_not_an_openssh_private_key_is_refused(text):
    with pytest.raises(ValueError):
        public_line_of_private(text)
