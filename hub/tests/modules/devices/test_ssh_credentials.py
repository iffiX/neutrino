"""How a device's stored credentials reach an SSH connection.

A device's config carries only references — a key id, a password id — so what
these pin is that each id is opened from the vault when the credentials are
built, and that a stale id yields no material rather than an error.
"""

import asyncio

import asyncssh
import pytest

from neutrino_hub.exceptions import KeyMaterialError
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
from tests.conftest import unlock_vault

PASSPHRASE = "opens-the-key"
LOGIN_PASSWORD = "a-password"  # scan: allow


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """A `config/` of this test's own, so nothing reads the real one."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def stored_key(passphrase: str | None = None) -> tuple[str, str]:
    """A key in the vault, as the Credentials page would have added it."""
    key = asyncssh.generate_private_key("ssh-ed25519")
    record = KeyRegistry().add(
        name="a key",
        private_key=key.export_private_key(passphrase=passphrase).decode(),
        passphrase=passphrase,
    )
    return record.id, key.get_fingerprint()


def stored_password(password: str) -> str:
    """A password in the vault, as the Credentials page would have sealed it."""
    record = SecretVault().add(
        kind="login", name="a password", secret={"password": password}
    )
    return record.id


def operator(credentials: SshCredentials, tmp_path) -> DeviceSshOperator:
    """An operator whose host keys are remembered in a file of its own."""
    return DeviceSshOperator(
        credentials=credentials,
        host_keys=DeviceHostKeyStore(path=tmp_path / "known_hosts"),
    )


def test_a_devices_key_id_is_opened_from_the_vault(config_dir):
    key_id, fingerprint = stored_key()

    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "key_id": key_id}
    )

    loaded = asyncssh.import_private_key(credentials.private_key)
    assert loaded.get_fingerprint() == fingerprint
    assert credentials.private_key_passphrase is None


def test_an_encrypted_key_carries_its_passphrase(config_dir):
    key_id, fingerprint = stored_key(PASSPHRASE)

    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "key_id": key_id}
    )

    assert credentials.private_key_passphrase == PASSPHRASE
    loaded = asyncssh.import_private_key(
        credentials.private_key, passphrase=credentials.private_key_passphrase
    )
    assert loaded.get_fingerprint() == fingerprint


def test_a_key_id_that_is_gone_leaves_no_material(config_dir, tmp_path):
    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "key_id": "absent"}
    )

    assert credentials.private_key is None
    assert "client_keys" not in operator(credentials, tmp_path)._connect_options()


def test_the_connection_is_given_a_loaded_key(config_dir, tmp_path):
    key_id, fingerprint = stored_key(PASSPHRASE)
    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "key_id": key_id}
    )

    options = operator(credentials, tmp_path)._connect_options()

    assert [key.get_fingerprint() for key in options["client_keys"]] == [fingerprint]
    assert "passphrase" not in options


def test_a_key_file_named_by_the_config_is_still_used(config_dir, tmp_path):
    key = asyncssh.generate_private_key("ssh-ed25519")
    path = tmp_path / "id_ed25519"
    path.write_text(key.export_private_key(passphrase=PASSPHRASE).decode())

    credentials = SshCredentials.from_dict(
        {
            "host": "192.168.100.2",
            "username": "iffi",
            "private_key_path": str(path),
            "private_key_passphrase": PASSPHRASE,
        }
    )
    options = operator(credentials, tmp_path)._connect_options()

    assert options["client_keys"] == [str(path)]
    assert options["passphrase"] == PASSPHRASE


def encrypted_key() -> str:
    key = asyncssh.generate_private_key("ssh-ed25519")
    return key.export_private_key(passphrase=PASSPHRASE).decode()


@pytest.mark.parametrize(
    "passphrase, code",
    [
        (None, "key_passphrase_not_stored"),
        ("not-the-passphrase", "key_passphrase_wrong"),
    ],
    ids=["no_passphrase", "wrong_passphrase"],
)
def test_a_vault_key_its_passphrase_does_not_open_is_refused_by_code(
    tmp_path, passphrase, code
):
    """asyncssh's ValueError left the probe and the request ended with 500."""
    credentials = SshCredentials(
        host="192.168.100.2",
        port=22,
        username="iffi",
        private_key=encrypted_key(),
        private_key_passphrase=passphrase,
    )

    with pytest.raises(KeyMaterialError) as refused:
        asyncio.run(operator(credentials, tmp_path).run_once("uname -s"))

    assert refused.value.code == code


def test_a_key_file_with_a_passphrase_and_none_stored_is_refused_by_code(tmp_path):
    """The install dialog asked for the passphrase and has no field for one."""
    path = tmp_path / "id_ed25519"
    path.write_text(encrypted_key())
    credentials = SshCredentials(
        host="127.0.0.1", port=1, username="iffi", private_key_path=str(path)
    )

    with pytest.raises(KeyMaterialError) as refused:
        asyncio.run(operator(credentials, tmp_path).run_once("uname -s"))

    assert refused.value.code == "key_passphrase_not_stored"


def test_a_password_device_offers_no_key(config_dir, tmp_path):
    credentials = SshCredentials.from_dict(
        {
            "host": "192.168.100.2",
            "username": "iffi",
            "login_id": stored_password(LOGIN_PASSWORD),
        }
    )

    options = operator(credentials, tmp_path)._connect_options()

    assert "client_keys" not in options
    assert options["password"] == LOGIN_PASSWORD


def test_a_login_id_is_opened_from_the_vault(config_dir):
    credentials = SshCredentials.from_dict(
        {
            "host": "192.168.100.2",
            "username": "iffi",
            "login_id": stored_password(LOGIN_PASSWORD),
        }
    )

    assert credentials.password == LOGIN_PASSWORD


def test_a_login_id_that_is_gone_leaves_no_material(config_dir, tmp_path):
    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "login_id": "absent"}
    )

    assert credentials.password is None
    assert "password" not in operator(credentials, tmp_path)._connect_options()


def test_a_login_id_naming_another_kind_leaves_no_material(config_dir):
    key_id, _ = stored_key()

    credentials = SshCredentials.from_dict(
        {"host": "192.168.100.2", "username": "iffi", "login_id": key_id}
    )

    assert credentials.password is None
