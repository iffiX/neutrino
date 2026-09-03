"""The SSH keys the panel holds, sealed in the credential vault.

A device carries a key id and nothing else, so what these pin is that the id
still resolves to usable material, that the material never appears in the store
in the clear, and that a bad paste is refused with the message that names its
own fix.
"""

import asyncssh
import pytest

from neutrino_hub.modules.credentials.constants import CREDENTIALS_VAULT_PATH
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.key_registry import KeyMaterialError, KeyRegistry
from tests.conftest import unlock_vault

PASSPHRASE = "opens-the-key"
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterialForTests"
NOT_A_KEY = "my key is in the drawer"  # scan: allow


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def generated_key(passphrase: str | None = None) -> tuple[str, str]:
    """A fresh ed25519 key as text, with its fingerprint."""
    key = asyncssh.generate_private_key("ssh-ed25519")
    exported = key.export_private_key(passphrase=passphrase).decode()
    return exported, key.get_fingerprint()


def test_a_stored_key_keeps_its_type_and_fingerprint(config_dir):
    text, fingerprint = generated_key()

    record = KeyRegistry().add(name="work laptop", private_key=text)

    assert record.name == "work laptop"
    assert record.key_type == "ssh-ed25519"
    assert record.fingerprint == fingerprint
    assert record.has_passphrase is False
    assert record.created_at


def test_the_material_is_sealed_rather_than_stored(config_dir):
    text, _ = generated_key()

    KeyRegistry().add(name="work laptop", private_key=text)

    stored = (config_dir / CREDENTIALS_VAULT_PATH).read_text()
    body = max(text.strip().splitlines(), key=len)
    assert body not in stored


def test_material_comes_back_as_it_was_pasted(config_dir):
    text, fingerprint = generated_key()
    record = KeyRegistry().add(name="work laptop", private_key=text)

    private_key, passphrase = KeyRegistry().material_for(record.id)

    assert passphrase is None
    assert asyncssh.import_private_key(private_key).get_fingerprint() == fingerprint


def test_an_encrypted_key_keeps_the_passphrase_that_opens_it(config_dir):
    text, fingerprint = generated_key(PASSPHRASE)

    record = KeyRegistry().add(
        name="encrypted", private_key=text, passphrase=PASSPHRASE
    )

    assert record.has_passphrase is True
    private_key, passphrase = KeyRegistry().material_for(record.id)
    assert passphrase == PASSPHRASE
    loaded = asyncssh.import_private_key(private_key, passphrase=passphrase)
    assert loaded.get_fingerprint() == fingerprint


def test_a_key_with_no_name_is_labelled_by_its_fingerprint(config_dir):
    text, fingerprint = generated_key()

    record = KeyRegistry().add(name="   ", private_key=text)

    assert record.name == fingerprint


def test_the_listing_holds_the_keys_and_nothing_else_in_the_vault(config_dir):
    text, _ = generated_key()
    key = KeyRegistry().add(name="work laptop", private_key=text)
    password = SecretVault().add(
        kind="login", name="a login", secret={"password": "not-a-key"}
    )

    assert [record.id for record in KeyRegistry().list_records()] == [key.id]
    assert KeyRegistry().get(password.id) is None
    assert KeyRegistry().has_key(password.id) is False
    assert KeyRegistry().has_key(key.id) is True


def test_an_unknown_id_is_not_a_key(config_dir):
    assert KeyRegistry().get("absent") is None
    assert KeyRegistry().has_key("absent") is False


def test_renaming_keeps_the_material(config_dir):
    text, fingerprint = generated_key()
    record = KeyRegistry().add(name="work laptop", private_key=text)

    renamed = KeyRegistry().rename(record.id, "  home desktop  ")

    assert renamed.name == "home desktop"
    assert renamed.fingerprint == fingerprint
    private_key, _ = KeyRegistry().material_for(record.id)
    assert asyncssh.import_private_key(private_key).get_fingerprint() == fingerprint


def test_renaming_refuses_a_blank_name_and_an_unknown_key(config_dir):
    text, _ = generated_key()
    record = KeyRegistry().add(name="work laptop", private_key=text)

    with pytest.raises(KeyMaterialError, match="a key needs a name"):
        KeyRegistry().rename(record.id, "  ")
    with pytest.raises(KeyMaterialError, match="no key with id"):
        KeyRegistry().rename("absent", "anything")


def test_deleting_takes_the_material_with_it(config_dir):
    text, _ = generated_key()
    record = KeyRegistry().add(name="work laptop", private_key=text)

    KeyRegistry().delete(record.id)

    assert KeyRegistry().get(record.id) is None
    assert KeyRegistry().list_records() == []
    with pytest.raises(KeyMaterialError):
        KeyRegistry().material_for(record.id)


def test_deleting_a_key_that_is_not_there_is_not_an_error(config_dir):
    KeyRegistry().delete("absent")


def test_a_public_key_is_refused_by_name(config_dir):
    with pytest.raises(KeyMaterialError, match="public key"):
        KeyRegistry().add(name="pasted the wrong file", private_key=PUBLIC_KEY)


def test_something_that_is_not_a_key_is_refused(config_dir):
    with pytest.raises(KeyMaterialError, match="no key was pasted"):
        KeyRegistry().add(name="empty", private_key="   ")
    with pytest.raises(KeyMaterialError, match="does not look like a private key"):
        KeyRegistry().add(name="prose", private_key=NOT_A_KEY)


def test_an_encrypted_key_without_its_passphrase_says_so(config_dir):
    text, _ = generated_key(PASSPHRASE)

    with pytest.raises(KeyMaterialError, match="enter its passphrase too"):
        KeyRegistry().add(name="encrypted", private_key=text)
    with pytest.raises(KeyMaterialError, match="does not open it"):
        KeyRegistry().add(name="encrypted", private_key=text, passphrase="wrong")

    assert KeyRegistry().list_records() == []
