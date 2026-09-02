"""The credential vault: sealing, binding, replacing, and rekeying."""

import base64
import json
import secrets
import stat

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.constants import CREDENTIALS_VAULT_PATH
from neutrino_hub.modules.credentials.vault import (
    SecretVault,
    VaultError,
    unwrap_master_key,
    wrap_master_key,
)

SEALED_BY_KIND = {
    "password": {"password": "hunter2hunter2"},  # scan: allow
    "ssh_key": {"private_key": "-----BEGIN FAKE KEY-----", "passphrase": "pp"},
    "api_token": {"api_key": "sk-test"},  # scan: allow
    "service_account": {"password": "svc-pw"},  # scan: allow
}


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def read_store(config_dir) -> dict:
    return json.loads((config_dir / CREDENTIALS_VAULT_PATH).read_text())


def write_store(config_dir, store: dict) -> None:
    (config_dir / CREDENTIALS_VAULT_PATH).write_text(json.dumps(store))


@pytest.mark.parametrize("kind", sorted(SEALED_BY_KIND))
def test_roundtrip(config_dir, kind):
    record = SecretVault().add(kind=kind, name=f"a {kind}", secret=SEALED_BY_KIND[kind])
    assert record.id
    assert record.kind == kind
    assert SecretVault().open(record.id) == SEALED_BY_KIND[kind]
    stored_text = (config_dir / CREDENTIALS_VAULT_PATH).read_text()
    for value in SEALED_BY_KIND[kind].values():
        assert value not in stored_text


def test_list_filters_by_kind(config_dir):
    vault = SecretVault()
    password = vault.add(kind="password", name="one", secret={"password": "x"})
    token = vault.add(kind="api_token", name="two", secret={"api_key": "y"})
    assert {r.id for r in vault.list_records()} == {password.id, token.id}
    assert [r.id for r in vault.list_records(kind="api_token")] == [token.id]
    with pytest.raises(VaultError):
        vault.list_records(kind="acme")


def test_open_unknown_id_is_refused(config_dir):
    with pytest.raises(VaultError):
        SecretVault().open("0" * 32)


def test_unknown_kind_is_refused(config_dir):
    with pytest.raises(VaultError):
        SecretVault().add(kind="acme", name="x", secret={"password": "p"})


def test_field_names_must_match_the_kind(config_dir):
    vault = SecretVault()
    with pytest.raises(VaultError):
        vault.add(kind="password", name="x", secret={})
    with pytest.raises(VaultError):
        vault.add(kind="password", name="x", secret={"password": "p", "note": "n"})
    record = vault.add(kind="ssh_key", name="x", secret={"private_key": "k"})
    assert SecretVault().open(record.id) == {"private_key": "k"}


def test_rename_delete_and_get(config_dir):
    vault = SecretVault()
    record = vault.add(kind="password", name="old", secret={"password": "p"})
    assert vault.rename(record.id, "new").name == "new"
    assert SecretVault().get(record.id).name == "new"
    vault.delete(record.id)
    assert SecretVault().get(record.id) is None
    with pytest.raises(VaultError):
        vault.delete(record.id)


def test_tampered_data_is_refused(config_dir):
    record = SecretVault().add(kind="password", name="x", secret={"password": "p"})
    store = read_store(config_dir)
    raw = bytearray(base64.b64decode(store["secrets"][record.id]["data"]))
    raw[0] ^= 0x01
    store["secrets"][record.id]["data"] = base64.b64encode(bytes(raw)).decode()
    write_store(config_dir, store)
    with pytest.raises(VaultError):
        SecretVault().open(record.id)


def test_ciphertexts_are_bound_to_their_ids(config_dir):
    vault = SecretVault()
    first = vault.add(kind="password", name="a", secret={"password": "pa"})
    second = vault.add(kind="password", name="b", secret={"password": "pb"})
    store = read_store(config_dir)
    one, two = store["secrets"][first.id], store["secrets"][second.id]
    one["nonce"], two["nonce"] = two["nonce"], one["nonce"]
    one["data"], two["data"] = two["data"], one["data"]
    write_store(config_dir, store)
    with pytest.raises(VaultError):
        SecretVault().open(first.id)
    with pytest.raises(VaultError):
        SecretVault().open(second.id)


def test_replace_changes_nonce_and_data(config_dir):
    vault = SecretVault()
    record = vault.add(kind="password", name="x", secret={"password": "old"})
    before = dict(read_store(config_dir)["secrets"][record.id])
    replaced = vault.replace(record.id, secret={"password": "new"})
    after = read_store(config_dir)["secrets"][record.id]
    assert replaced.id == record.id
    assert replaced.kind == "password"
    assert after["nonce"] != before["nonce"]
    assert after["data"] != before["data"]
    assert SecretVault().open(record.id) == {"password": "new"}


def test_rekey_preserves_secrets_and_changes_the_key(config_dir):
    vault = SecretVault()
    password = vault.add(kind="password", name="a", secret={"password": "pa"})
    token = vault.add(kind="api_token", name="b", secret={"api_key": "kb"})
    key_path = config_dir / "credentials" / "vault.key"
    old_key = key_path.read_text()
    assert vault.rekey() == 2
    assert key_path.read_text() != old_key
    assert not (config_dir / "credentials" / "vault.key.new").exists()
    assert SecretVault().open(password.id) == {"password": "pa"}
    assert SecretVault().open(token.id) == {"api_key": "kb"}


def test_leftover_rekey_key_is_discarded_when_the_old_key_still_opens(config_dir):
    record = SecretVault().add(kind="password", name="x", secret={"password": "p"})
    new_path = config_dir / "credentials" / "vault.key.new"
    new_path.write_text(secrets.token_bytes(32).hex())
    assert SecretVault().open(record.id) == {"password": "p"}
    assert not new_path.exists()


def test_interrupted_rekey_is_finished_from_the_new_key(config_dir):
    vault = SecretVault()
    record = vault.add(kind="password", name="x", secret={"password": "p"})
    key_path = config_dir / "credentials" / "vault.key"
    old_key = key_path.read_text()
    vault.rekey()
    new_key = key_path.read_text()
    (config_dir / "credentials" / "vault.key.new").write_text(new_key)
    key_path.write_text(old_key)
    assert SecretVault().open(record.id) == {"password": "p"}
    assert key_path.read_text() == new_key
    assert not (config_dir / "credentials" / "vault.key.new").exists()


def test_key_file_and_directory_modes(config_dir):
    SecretVault().add(kind="password", name="x", secret={"password": "p"})
    key_path = config_dir / "credentials" / "vault.key"
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_path.parent.stat().st_mode) == 0o700


def test_wrap_and_unwrap_master_key():
    key = secrets.token_bytes(32)
    wrapped = wrap_master_key(key, "correct horse")
    assert wrapped["kdf"] == "scrypt"
    assert unwrap_master_key(wrapped, "correct horse") == key
    with pytest.raises(VaultError):
        unwrap_master_key(wrapped, "wrong horse")


def test_hostile_wrap_factors_are_refused():
    wrapped = wrap_master_key(b"k" * 32, "pass")
    wrapped["n"] = 2**30
    with pytest.raises(VaultError):
        unwrap_master_key(wrapped, "pass")
