"""The credential vault: sealing, binding, the passphrase wrap, and the lock."""

import base64
import json
import secrets
import stat

import pytest

import neutrino_hub.utils.json_file
from neutrino_hub.modules.credentials.constants import CREDENTIALS_VAULT_PATH
from neutrino_hub.exceptions import VaultLockedError, VaultPassphraseError
from neutrino_hub.modules.credentials.vault import (
    VAULT_RECORDS_AAD,
    SecretVault,
    seal_bytes,
    unseal_bytes,
    unwrap_data_key,
    wrap_data_key,
)
from tests.conftest import unlock_vault

SEALED_BY_KIND = {
    "token": {"value": "sk-test"},  # scan: allow
    "login": {"username": "backup", "password": "hunter2hunter2"},  # scan: allow
    # The passphrase is long on purpose: the not-in-the-file assertions hunt
    # these strings inside base64 ciphertext, where a two-character needle
    # lands by chance often enough to flake.
    "ssh_key": {
        "private_key": "-----BEGIN FAKE KEY-----",
        "passphrase": "a-needle-passphrase",  # scan: allow
    },
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


def read_inner(config_dir) -> dict:
    sealed = read_store(config_dir).get("sealed")
    if not sealed:
        return {}
    return json.loads(unseal_bytes(sealed, VAULT_RECORDS_AAD))


def write_inner(config_dir, records: dict) -> None:
    store = read_store(config_dir)
    store["sealed"] = seal_bytes(json.dumps(records).encode(), VAULT_RECORDS_AAD)
    write_store(config_dir, store)


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
    password = vault.add(kind="login", name="one", secret={"password": "x"})
    token = vault.add(kind="token", name="two", secret={"value": "y"})
    assert {r.id for r in vault.list_records()} == {password.id, token.id}
    assert [r.id for r in vault.list_records(kind="token")] == [token.id]
    with pytest.raises(ValueError):
        vault.list_records(kind="acme")


def test_open_unknown_id_is_refused(config_dir):
    with pytest.raises(ValueError):
        SecretVault().open("0" * 32)


def test_unknown_kind_is_refused(config_dir):
    with pytest.raises(ValueError):
        SecretVault().add(kind="acme", name="x", secret={"password": "p"})


def test_field_names_must_match_the_kind(config_dir):
    vault = SecretVault()
    with pytest.raises(ValueError):
        vault.add(kind="login", name="x", secret={})
    with pytest.raises(ValueError):
        vault.add(kind="login", name="x", secret={"password": "p", "note": "n"})
    record = vault.add(kind="ssh_key", name="x", secret={"private_key": "k"})
    assert SecretVault().open(record.id) == {"private_key": "k"}


def test_delete_and_get(config_dir):
    vault = SecretVault()
    record = vault.add(kind="login", name="old", secret={"password": "p"})
    assert SecretVault().get(record.id).name == "old"
    vault.delete(record.id)
    assert SecretVault().get(record.id) is None
    with pytest.raises(ValueError):
        vault.delete(record.id)


def test_tampered_data_is_refused(config_dir):
    record = SecretVault().add(kind="login", name="x", secret={"password": "p"})
    records = read_inner(config_dir)
    raw = bytearray(base64.b64decode(records[record.id]["data"]))
    raw[0] ^= 0x01
    records[record.id]["data"] = base64.b64encode(bytes(raw)).decode()
    write_inner(config_dir, records)
    with pytest.raises(ValueError):
        SecretVault().open(record.id)


def test_ciphertexts_are_bound_to_their_ids(config_dir):
    vault = SecretVault()
    first = vault.add(kind="login", name="a", secret={"password": "pa"})
    second = vault.add(kind="login", name="b", secret={"password": "pb"})
    records = read_inner(config_dir)
    one, two = records[first.id], records[second.id]
    one["nonce"], two["nonce"] = two["nonce"], one["nonce"]
    one["data"], two["data"] = two["data"], one["data"]
    write_inner(config_dir, records)
    with pytest.raises(ValueError):
        SecretVault().open(first.id)
    with pytest.raises(ValueError):
        SecretVault().open(second.id)


def test_replace_changes_nonce_and_data(config_dir):
    vault = SecretVault()
    record = vault.add(kind="login", name="x", secret={"password": "old"})
    before = dict(read_inner(config_dir)[record.id])
    replaced = vault.replace(record.id, secret={"password": "new"})
    after = read_inner(config_dir)[record.id]
    assert replaced.id == record.id
    assert replaced.kind == "login"
    assert after["nonce"] != before["nonce"]
    assert after["data"] != before["data"]
    assert SecretVault().open(record.id) == {"password": "new"}


def test_update_meta_leaves_the_seal_alone(config_dir):
    vault = SecretVault()
    record = vault.add(
        kind="login",
        name="nas",
        secret={"password": "p"},
        meta={"note": "the NAS"},
    )
    before = dict(read_inner(config_dir)[record.id])
    updated = vault.update_meta(record.id, {"note": "the archive"})
    after = read_inner(config_dir)[record.id]
    assert updated.meta == {"note": "the archive"}
    assert after["nonce"] == before["nonce"]
    assert after["data"] == before["data"]
    assert SecretVault().open(record.id) == {"password": "p"}
    with pytest.raises(ValueError):
        vault.update_meta("0" * 32, {"note": "the archive"})


def test_an_unsupported_store_version_is_refused(config_dir):
    write_store(config_dir, {"version": 1, "secrets": {}})
    with pytest.raises(ValueError, match="version"):
        SecretVault().get("anything")


# --- the lock ---------------------------------------------------------------


def test_a_locked_vault_refuses_what_needs_the_key(locked_dir):
    vault = SecretVault()
    assert vault.is_locked()
    with pytest.raises(VaultLockedError):
        vault.add(kind="login", name="x", secret={"password": "p"})
    with pytest.raises(VaultLockedError):
        vault.open("0" * 32)
    with pytest.raises(VaultLockedError):
        vault.change_passphrase(PASSPHRASE)
    with pytest.raises(VaultLockedError):
        seal_bytes(b"payload", b"purpose")


def test_a_locked_vault_hides_even_the_names(config_dir):
    SecretVault().add(kind="login", name="the NAS", secret={"password": "p"})
    (config_dir / "state" / "vault.key").unlink()
    vault = SecretVault()
    assert vault.is_locked()
    with pytest.raises(VaultLockedError):
        vault.list_records()
    with pytest.raises(VaultLockedError):
        vault.get("anything")
    with pytest.raises(VaultLockedError):
        vault.delete("anything")


def test_the_file_says_nothing_about_what_it_holds(config_dir):
    SecretVault().initialize(PASSPHRASE)
    SecretVault().add(
        kind="login",
        name="the NAS archive",
        secret={"username": "backup", "password": "hunter2hunter2"},  # scan: allow
        meta={"note": "a distinctive note"},
    )
    raw = (config_dir / CREDENTIALS_VAULT_PATH).read_text()
    assert sorted(json.loads(raw)) == ["sealed", "version", "wrapped_key"]
    for readable in ("NAS", "login", "backup", "hunter2", "distinctive"):
        assert readable not in raw


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
    with pytest.raises(ValueError) as refusal:
        unwrap_data_key(PASSPHRASE, {"kdf": "acme"})
    assert not isinstance(refusal.value, VaultPassphraseError)
    with pytest.raises(ValueError) as refusal:
        unwrap_data_key(PASSPHRASE, "not an object")
    assert not isinstance(refusal.value, VaultPassphraseError)


def test_hostile_wrap_factors_are_refused():
    wrapped = wrap_data_key(PASSPHRASE, secrets.token_bytes(32))
    wrapped["n"] = 2**30
    with pytest.raises(ValueError):
        unwrap_data_key(PASSPHRASE, wrapped)


def test_initialize_generates_wraps_and_unlocks(locked_dir):
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
    vault.add(kind="login", name="x", secret={"password": "p"})
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
    record = vault.add(kind="login", name="x", secret={"password": "p"})
    sealed_before = dict(read_inner(config_dir)[record.id])
    key_before = (config_dir / "state" / "vault.key").read_text()

    vault.change_passphrase("Another-passphrase-2!")

    assert read_inner(config_dir)[record.id] == sealed_before
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
    with pytest.raises(ValueError):
        unseal_bytes(sealed, b"something_else")
    with pytest.raises(ValueError):
        unseal_bytes({"nonce": "!", "data": "!"}, b"agent_tls:key")
