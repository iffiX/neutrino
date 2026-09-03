"""The credential vault: sealing, binding, the passphrase wrap, and the lock."""

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
    VaultLockedError,
    VaultPassphraseError,
    seal_bytes,
    unseal_bytes,
    unwrap_data_key,
    wrap_data_key,
)
from tests.conftest import unlock_vault

SEALED_BY_KIND = {
    "password": {"password": "hunter2hunter2"},  # scan: allow
    "ssh_key": {"private_key": "-----BEGIN FAKE KEY-----", "passphrase": "pp"},
    "api_token": {"api_key": "sk-test"},  # scan: allow
    "service_account": {"password": "svc-pw"},  # scan: allow
}
PASSPHRASE = "A-vault-passphrase-16!"  # scan: allow


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


@pytest.fixture()
def locked_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(neutrino_hub.utils.json_file, "UTILS_CONFIG_DIR", tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    return tmp_path


def read_store(config_dir) -> dict:
    return json.loads((config_dir / CREDENTIALS_VAULT_PATH).read_text())


def write_store(config_dir, store: dict) -> None:
    path = config_dir / CREDENTIALS_VAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store))


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


def test_update_meta_leaves_the_seal_alone(config_dir):
    vault = SecretVault()
    record = vault.add(
        kind="service_account",
        name="nas",
        secret={"password": "p"},
        meta={"username": "backup"},
    )
    before = dict(read_store(config_dir)["secrets"][record.id])
    updated = vault.update_meta(record.id, {"username": "archive"})
    after = read_store(config_dir)["secrets"][record.id]
    assert updated.meta == {"username": "archive"}
    assert after["nonce"] == before["nonce"]
    assert after["data"] == before["data"]
    assert SecretVault().open(record.id) == {"password": "p"}
    with pytest.raises(VaultError):
        vault.update_meta("0" * 32, {"username": "archive"})


def test_an_unsupported_store_version_is_refused(config_dir):
    write_store(config_dir, {"version": 1, "secrets": {}})
    with pytest.raises(VaultError, match="version"):
        SecretVault().get("anything")


# --- the lock ---------------------------------------------------------------


def test_a_locked_vault_refuses_what_needs_the_key(locked_dir):
    vault = SecretVault()
    assert vault.is_locked()
    with pytest.raises(VaultLockedError):
        vault.add(kind="password", name="x", secret={"password": "p"})
    with pytest.raises(VaultLockedError):
        vault.open("0" * 32)
    with pytest.raises(VaultLockedError):
        vault.change_passphrase(PASSPHRASE)
    with pytest.raises(VaultLockedError):
        seal_bytes(b"payload", b"purpose")


def test_a_locked_vault_still_lists_and_deletes(locked_dir):
    write_store(
        locked_dir,
        {
            "version": 2,
            "secrets": {
                "abc123": {"name": "a key", "kind": "ssh_key", "nonce": "", "data": ""}
            },
        },
    )
    vault = SecretVault()
    assert [record.id for record in vault.list_records()] == ["abc123"]
    vault.delete("abc123")
    assert vault.list_records() == []


# --- the passphrase wrap ----------------------------------------------------


def test_wrap_and_unwrap_roundtrip():
    data_key = secrets.token_bytes(32)
    wrapped = wrap_data_key(PASSPHRASE, data_key)
    assert unwrap_data_key(PASSPHRASE, wrapped) == data_key
    assert data_key.hex() not in json.dumps(wrapped)


def test_a_wrong_passphrase_is_its_own_refusal():
    wrapped = wrap_data_key(PASSPHRASE, secrets.token_bytes(32))
    with pytest.raises(VaultPassphraseError):
        unwrap_data_key("Not-the-passphrase-1!", wrapped)


def test_a_malformed_wrap_is_refused_before_the_passphrase_matters():
    with pytest.raises(VaultError) as refusal:
        unwrap_data_key(PASSPHRASE, {"kdf": "acme"})
    assert not isinstance(refusal.value, VaultPassphraseError)
    with pytest.raises(VaultError) as refusal:
        unwrap_data_key(PASSPHRASE, "not an object")
    assert not isinstance(refusal.value, VaultPassphraseError)


def test_hostile_wrap_factors_are_refused():
    wrapped = wrap_data_key(PASSPHRASE, secrets.token_bytes(32))
    wrapped["n"] = 2**30
    with pytest.raises(VaultError):
        unwrap_data_key(PASSPHRASE, wrapped)


def test_initialize_mints_wraps_and_unlocks(locked_dir):
    vault = SecretVault()
    assert vault.initialize(PASSPHRASE) is True
    assert not vault.is_locked()
    key_path = locked_dir / "state" / "vault.key"
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    wrapped = read_store(locked_dir)["wrapped_key"]
    assert unwrap_data_key(PASSPHRASE, wrapped) == bytes.fromhex(
        key_path.read_text().strip()
    )


def test_initialize_converges_on_a_wrapped_store(locked_dir):
    vault = SecretVault()
    vault.initialize(PASSPHRASE)
    data_key = (locked_dir / "state" / "vault.key").read_text()
    (locked_dir / "state" / "vault.key").unlink()
    assert vault.initialize(PASSPHRASE) is False
    assert (locked_dir / "state" / "vault.key").read_text() == data_key


def test_initialize_never_rekeys_a_store_with_secrets(locked_dir):
    vault = SecretVault()
    vault.initialize(PASSPHRASE)
    vault.add(kind="password", name="x", secret={"password": "p"})
    with pytest.raises(VaultPassphraseError):
        vault.initialize("Not-the-passphrase-1!")


def test_initialize_replaces_an_empty_store_whose_passphrase_is_lost(locked_dir):
    vault = SecretVault()
    vault.initialize(PASSPHRASE)
    before = read_store(locked_dir)["wrapped_key"]
    assert vault.initialize("Another-passphrase-2!") is True
    assert read_store(locked_dir)["wrapped_key"] != before


def test_change_passphrase_rewraps_and_nothing_sealed_moves(config_dir):
    vault = SecretVault()
    vault.initialize(PASSPHRASE)
    record = vault.add(kind="password", name="x", secret={"password": "p"})
    sealed_before = dict(read_store(config_dir)["secrets"][record.id])
    key_before = (config_dir / "state" / "vault.key").read_text()

    vault.change_passphrase("Another-passphrase-2!")

    assert read_store(config_dir)["secrets"][record.id] == sealed_before
    assert (config_dir / "state" / "vault.key").read_text() == key_before
    wrapped = read_store(config_dir)["wrapped_key"]
    with pytest.raises(VaultPassphraseError):
        unwrap_data_key(PASSPHRASE, wrapped)
    assert unwrap_data_key("Another-passphrase-2!", wrapped) == bytes.fromhex(
        key_before.strip()
    )
    assert SecretVault().open(record.id) == {"password": "p"}


# --- byte payloads under the data key ---------------------------------------


def test_seal_bytes_binds_to_its_purpose(config_dir):
    payload = secrets.token_bytes(120)
    sealed = seal_bytes(payload, b"agent_tls:key")
    assert unseal_bytes(sealed, b"agent_tls:key") == payload
    with pytest.raises(VaultError):
        unseal_bytes(sealed, b"something_else")
    with pytest.raises(VaultError):
        unseal_bytes({"nonce": "!", "data": "!"}, b"agent_tls:key")
