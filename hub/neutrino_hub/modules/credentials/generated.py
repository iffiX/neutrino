"""The secrets the hub generated for the machines, as the Credentials page
lists them.

Each stays sealed where its module keeps it: an account's SMB password in
``samba.json``, the seat password in ``rdp.json`` and an account's SSH key in
``ssh_server.json``. A listing names each by its machine, its kind and its
account, an SSH key with its fingerprint, and holds no value.
"""

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.credentials.constants import (
    CREDENTIALS_GENERATED_SEAT_PASSWORD,
    CREDENTIALS_GENERATED_SMB_PASSWORD,
    CREDENTIALS_GENERATED_SSH_KEY,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_SAMBA_MODULE,
    DEVICE_SAMBA_PASSWORD_KEY,
    DEVICE_SSH_SERVER_KEY_KEY,
    DEVICE_SSH_SERVER_MODULE,
)


def generated_items(desired_states, device_id: str) -> list:
    """Every secret the hub generated for one machine.

    Args:
        desired_states: The :class:`DesiredStateStore`.
        device_id: The machine.

    Returns:
        ``{kind, account, fingerprint}`` items: an ``smb_password`` per
        account the file share enables, the ``seat_password`` while the
        machine has one, and an ``ssh_key`` per account the SSH server
        enables. ``account`` is empty for the seat password, and
        ``fingerprint`` is empty but on an SSH key.
    """
    items = [
        {"kind": CREDENTIALS_GENERATED_SMB_PASSWORD, "account": account}
        for account in desired_states.enabled_accounts(device_id, DEVICE_SAMBA_MODULE)
    ]
    if desired_states.has_seat_password(device_id):
        items.append({"kind": CREDENTIALS_GENERATED_SEAT_PASSWORD, "account": ""})
    items += [
        {
            "kind": CREDENTIALS_GENERATED_SSH_KEY,
            "account": account,
            "fingerprint": desired_states.account_key_fingerprint(device_id, account),
        }
        for account in desired_states.enabled_accounts(
            device_id, DEVICE_SSH_SERVER_MODULE
        )
    ]
    return [{"fingerprint": "", **item} for item in items]


def is_generated(desired_states, device_id: str, kind: str, account: str) -> bool:
    """Whether one machine has one generated secret.

    Args:
        desired_states: The :class:`DesiredStateStore`.
        device_id: The machine.
        kind: The secret's kind.
        account: The account; empty for the seat password.

    Returns:
        True when :func:`generated_items` lists it.
    """
    return any(
        item["kind"] == kind and item["account"] == account
        for item in generated_items(desired_states, device_id)
    )


def generated_password(desired_states, device_id: str, kind: str, account: str) -> str:
    """One generated password, opened.

    Args:
        desired_states: The :class:`DesiredStateStore`.
        device_id: The machine.
        kind: ``smb_password`` or ``seat_password``.
        account: The account; empty for the seat password.

    Returns:
        The password.

    Raises:
        KeyError: When the machine has no such password.
        VaultLockedError: When the seal does not open on this box.
    """
    if kind == CREDENTIALS_GENERATED_SEAT_PASSWORD:
        if not desired_states.has_seat_password(device_id):
            raise KeyError(kind)
        value = desired_states.seat_password(device_id)
    elif kind == CREDENTIALS_GENERATED_SMB_PASSWORD:
        if account not in desired_states.enabled_accounts(
            device_id, DEVICE_SAMBA_MODULE
        ):
            raise KeyError(account)
        value = desired_states.account_secret(
            device_id, DEVICE_SAMBA_MODULE, account, DEVICE_SAMBA_PASSWORD_KEY
        )
    else:
        raise KeyError(kind)
    if not value:
        raise VaultLockedError()
    return value


def rotate_generated(desired_states, device_id: str, kind: str, account: str) -> None:
    """Generate one secret again and seal it where its module keeps it.

    Args:
        desired_states: The :class:`DesiredStateStore`.
        device_id: The machine.
        kind: The secret's kind.
        account: The account; empty for the seat password.

    Raises:
        KeyError: When the machine has no such secret.
        VaultLockedError: When there is no data key to seal it under.
        OSError: When the module's file cannot be written.
    """
    if not is_generated(desired_states, device_id, kind, account):
        raise KeyError(kind)
    if kind == CREDENTIALS_GENERATED_SEAT_PASSWORD:
        desired_states.reset_seat_password(device_id)
    elif kind == CREDENTIALS_GENERATED_SMB_PASSWORD:
        desired_states.rotate_account_secret(
            device_id, DEVICE_SAMBA_MODULE, account, DEVICE_SAMBA_PASSWORD_KEY
        )
    else:
        desired_states.rotate_account_secret(
            device_id, DEVICE_SSH_SERVER_MODULE, account, DEVICE_SSH_SERVER_KEY_KEY
        )
