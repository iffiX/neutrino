"""The description table: every device module the hub administers, one row each.

A row names the module's kind, its configuration file under
``config/devices/<id>/``, whether it runs one instance per enabled account
(the account layer), the fields the vault seals in each account's record,
the published entry's ``description_code`` and title, and the panel the
machine page draws it with. The eight account-layer modules share one
router, one panel and one state composition, each driven by its row; every
other kind has its own router and panel and reads its row for the rest.
"""

from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import (
    DEVICE_AYAKALEAF_INVITE_SECRET_AAD,
    DEVICE_AYAKALEAF_INVITE_SECRET_KEY,
    DEVICE_AYAKALEAF_MODULE,
    DEVICE_AYAKALEAF_PASSWORD_AAD,
    DEVICE_AYAKALEAF_PASSWORD_KEY,
    DEVICE_AYAKALEAF_SECRET_AAD,
    DEVICE_AYAKALEAF_SECRET_BYTES,
    DEVICE_AYAKALEAF_SECRET_KEY,
    DEVICE_AYAKALEAF_SESSION_SECRET_AAD,
    DEVICE_AYAKALEAF_SESSION_SECRET_KEY,
    DEVICE_CLOUDCLI_MODULE,
    DEVICE_CLOUDCLI_PASSWORD_AAD,
    DEVICE_CLOUDCLI_PASSWORD_KEY,
    DEVICE_CLOUDCLI_SECRET_AAD,
    DEVICE_CLOUDCLI_SECRET_BYTES,
    DEVICE_CLOUDCLI_SECRET_KEY,
    DEVICE_CODE_SERVER_MODULE,
    DEVICE_CODE_SERVER_SECRET_AAD,
    DEVICE_CODE_SERVER_SECRET_BYTES,
    DEVICE_CODE_SERVER_SECRET_KEY,
    DEVICE_CODEG_MODULE,
    DEVICE_CODEG_SECRET_AAD,
    DEVICE_CODEG_SECRET_BYTES,
    DEVICE_CODEG_SECRET_KEY,
    DEVICE_GITEA_MODULE,
    DEVICE_HERMES_WEBUI_MODULE,
    DEVICE_HERMES_WEBUI_PASSWORD_AAD,
    DEVICE_HERMES_WEBUI_PASSWORD_KEY,
    DEVICE_HERMES_WEBUI_SECRET_AAD,
    DEVICE_HERMES_WEBUI_SECRET_BYTES,
    DEVICE_HERMES_WEBUI_SECRET_KEY,
    DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
    DEVICE_MODULE_KIND_AGENT,
    DEVICE_MODULE_KIND_CONTAINER,
    DEVICE_MODULE_KIND_SERVICE_ACCOUNT,
    DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
    DEVICE_MODULE_PANEL_INSTANCES,
    DEVICE_PODMAN_MODULE,
    DEVICE_REMOTE_DESKTOP_MODULE,
    DEVICE_SAMBA_MODULE,
    DEVICE_SAMBA_PASSWORD_AAD,
    DEVICE_SAMBA_PASSWORD_BYTES,
    DEVICE_SAMBA_PASSWORD_KEY,
    DEVICE_SIYUAN_ACCESS_CODE_AAD,
    DEVICE_SIYUAN_ACCESS_CODE_KEY,
    DEVICE_SIYUAN_MODULE,
    DEVICE_SIYUAN_SECRET_AAD,
    DEVICE_SIYUAN_SECRET_BYTES,
    DEVICE_SIYUAN_SECRET_KEY,
    DEVICE_SSH_SERVER_KEY_AAD,
    DEVICE_SSH_SERVER_KEY_KEY,
    DEVICE_SSH_SERVER_MODULE,
    DEVICE_TERMINAL_MODULE,
    DEVICE_VSCODE_MODULE,
    DEVICE_VSCODE_TOKEN_AAD,
    DEVICE_VSCODE_TOKEN_BYTES,
    DEVICE_VSCODE_TOKEN_KEY,
)
from neutrino_hub.modules.services.constants import (
    SERVICES_AYAKALEAF_TITLE,
    SERVICES_DESCRIPTION_AYAKALEAF_MODULE,
    SERVICES_DESCRIPTION_CLOUDCLI_MODULE,
    SERVICES_DESCRIPTION_CODE_SERVER_MODULE,
    SERVICES_DESCRIPTION_CODEG_MODULE,
    SERVICES_DESCRIPTION_CONTAINER,
    SERVICES_DESCRIPTION_GITEA_MODULE,
    SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
    SERVICES_DESCRIPTION_SAMBA_MODULE,
    SERVICES_DESCRIPTION_SIYUAN_MODULE,
    SERVICES_DESCRIPTION_SSH_SERVER_MODULE,
    SERVICES_DESCRIPTION_VSCODE_MODULE,
    SERVICES_GITEA_TITLE,
    SERVICES_HERMES_WEBUI_TITLE,
    SERVICES_SSH_SERVER_TITLE,
)

# How a sealed field's fresh value is made: random bytes in base64url, or an
# Ed25519 key pair whose private half is the sealed value.
SEALED_KIND_TOKEN = "token"
SEALED_KIND_SSH_KEY = "ssh_key"


@dataclass(frozen=True)
class SealedField:
    """One field the vault seals in an account's record.

    Attributes:
        key: The key the seal is stored under in the module's file.
        opened_key: The key the opened value takes in the state the agent is
            sent.
        aad: What the seal is bound to.
        secret_bytes: How many random bytes a fresh token is made of.
        kind: ``token`` for random bytes, ``ssh_key`` for an Ed25519 key.
    """

    key: str
    opened_key: str
    aad: bytes
    secret_bytes: int = 0
    kind: str = SEALED_KIND_TOKEN


@dataclass(frozen=True)
class DeviceModuleRow:
    """One module as the hub describes it.

    Attributes:
        name: The manifest name.
        kind: One of the five kinds, ``DEVICE_MODULE_KIND_*``.
        config_file: The module's file under ``config/devices/<id>/``.
        is_account_layer: Whether the module runs one instance per enabled
            account and keeps its enabled accounts in its file.
        sealed_fields: The fields the vault seals in each account's record,
            or in the file itself for a container module, in the order the
            state carries them opened; empty for a module that keeps no
            secret.
        description_code: The published entry's ``description_code``; empty
            for a module that publishes nothing.
        entry_title: The published app's title, with ``{account}`` for an
            instance's; empty for a module whose entries are titled by what
            they publish.
        panel: The panel the machine page draws the module with.
        is_in_picker: Whether the catalog offers the module; false for one
            the agent carries, which is always a tab.
        is_login_named: Whether each instance runs as its account's login on
            Windows, whose password the state carries there.
        has_forwarder: Whether the agent's forwarder is in front of each
            instance, which takes the app's ``local_name`` and the entry's
            ``cookie_name``.
        token_field: The sealed field the ``service`` frame's token comes
            from; empty for a module that hands no token.
        is_token_minted: Whether the token is minted from the field for one
            open, or is the field's own value.
        config_head: The fields that lead the module's configuration in the
            state, as ``(key, value)`` pairs.
        is_gateway_used: Whether the module calls the AI gateway, which
            opens the agent's AI gateway forward while the module is
            installed; a container module's containers also have the
            gateway's port relayed on the hub's own machine, and a program
            run as an account holds one key per enabled account.
    """

    name: str
    kind: str
    config_file: str
    is_account_layer: bool = False
    sealed_fields: tuple = ()
    description_code: str = ""
    entry_title: str = ""
    panel: str = ""
    is_in_picker: bool = True
    is_login_named: bool = False
    has_forwarder: bool = False
    token_field: str = ""
    is_token_minted: bool = False
    config_head: tuple = ()
    is_gateway_used: bool = False

    def sealed_field(self, key: str) -> SealedField:
        """The sealed field stored under one key.

        Args:
            key: The key the seal is stored under.

        Returns:
            The field.

        Raises:
            KeyError: When the row seals no such field.
        """
        for sealed in self.sealed_fields:
            if sealed.key == key:
                return sealed
        raise KeyError(key)


def _row(name: str, kind: str, **fields) -> DeviceModuleRow:
    """One row, its file and panel named after the module unless given."""
    fields.setdefault("config_file", f"{name}.json")
    fields.setdefault("panel", name)
    return DeviceModuleRow(name=name, kind=kind, **fields)


# The rows in the order the machine page lists them: the modules every system
# runs first.
DEVICE_MODULE_ROWS = (
    _row(
        DEVICE_SAMBA_MODULE,
        DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_SAMBA_PASSWORD_KEY,
                opened_key="password",
                aad=DEVICE_SAMBA_PASSWORD_AAD,
                secret_bytes=DEVICE_SAMBA_PASSWORD_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_SAMBA_MODULE,
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        token_field=DEVICE_SAMBA_PASSWORD_KEY,
    ),
    _row(
        DEVICE_TERMINAL_MODULE,
        DEVICE_MODULE_KIND_AGENT,
        is_account_layer=True,
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_in_picker=False,
        is_login_named=True,
    ),
    _row(
        DEVICE_SSH_SERVER_MODULE,
        DEVICE_MODULE_KIND_AGENT,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_SSH_SERVER_KEY_KEY,
                opened_key="authorized_key",
                aad=DEVICE_SSH_SERVER_KEY_AAD,
                kind=SEALED_KIND_SSH_KEY,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_SSH_SERVER_MODULE,
        entry_title=SERVICES_SSH_SERVER_TITLE,
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_in_picker=False,
        is_login_named=True,
        token_field=DEVICE_SSH_SERVER_KEY_KEY,
    ),
    _row(DEVICE_REMOTE_DESKTOP_MODULE, DEVICE_MODULE_KIND_AGENT, is_in_picker=False),
    _row(
        DEVICE_GITEA_MODULE,
        DEVICE_MODULE_KIND_SERVICE_ACCOUNT,
        description_code=SERVICES_DESCRIPTION_GITEA_MODULE,
        entry_title=SERVICES_GITEA_TITLE,
    ),
    _row(
        DEVICE_VSCODE_MODULE,
        DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_VSCODE_TOKEN_KEY,
                opened_key="token",
                aad=DEVICE_VSCODE_TOKEN_AAD,
                secret_bytes=DEVICE_VSCODE_TOKEN_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_VSCODE_MODULE,
        entry_title="VS Code ({account})",
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_login_named=True,
        token_field=DEVICE_VSCODE_TOKEN_KEY,
        is_token_minted=False,
        config_head=(("address", ""),),
    ),
    _row(
        DEVICE_CODE_SERVER_MODULE,
        DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_CODE_SERVER_SECRET_KEY,
                opened_key="secret",
                aad=DEVICE_CODE_SERVER_SECRET_AAD,
                secret_bytes=DEVICE_CODE_SERVER_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_CODE_SERVER_MODULE,
        entry_title="code-server ({account})",
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        has_forwarder=True,
        token_field=DEVICE_CODE_SERVER_SECRET_KEY,
        is_token_minted=True,
    ),
    _row(
        DEVICE_CLOUDCLI_MODULE,
        DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_CLOUDCLI_PASSWORD_KEY,
                opened_key="web_password",
                aad=DEVICE_CLOUDCLI_PASSWORD_AAD,
                secret_bytes=DEVICE_CLOUDCLI_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_CLOUDCLI_SECRET_KEY,
                opened_key="token_secret",
                aad=DEVICE_CLOUDCLI_SECRET_AAD,
                secret_bytes=DEVICE_CLOUDCLI_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_CLOUDCLI_MODULE,
        entry_title="CloudCLI ({account})",
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_login_named=True,
        has_forwarder=True,
        token_field=DEVICE_CLOUDCLI_SECRET_KEY,
        is_token_minted=True,
    ),
    _row(
        DEVICE_CODEG_MODULE,
        DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_CODEG_SECRET_KEY,
                opened_key="secret",
                aad=DEVICE_CODEG_SECRET_AAD,
                secret_bytes=DEVICE_CODEG_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_CODEG_MODULE,
        entry_title="Codeg ({account})",
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_login_named=True,
        has_forwarder=True,
        token_field=DEVICE_CODEG_SECRET_KEY,
        is_token_minted=True,
    ),
    _row(
        DEVICE_SIYUAN_MODULE,
        DEVICE_MODULE_KIND_ACCOUNT_PROGRAM,
        is_account_layer=True,
        sealed_fields=(
            SealedField(
                key=DEVICE_SIYUAN_SECRET_KEY,
                opened_key="secret",
                aad=DEVICE_SIYUAN_SECRET_AAD,
                secret_bytes=DEVICE_SIYUAN_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_SIYUAN_ACCESS_CODE_KEY,
                opened_key="access_code",
                aad=DEVICE_SIYUAN_ACCESS_CODE_AAD,
                secret_bytes=DEVICE_SIYUAN_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_SIYUAN_MODULE,
        entry_title="SiYuan ({account})",
        panel=DEVICE_MODULE_PANEL_INSTANCES,
        is_login_named=True,
        has_forwarder=True,
        token_field=DEVICE_SIYUAN_SECRET_KEY,
        is_token_minted=True,
        is_gateway_used=True,
    ),
    _row(
        DEVICE_PODMAN_MODULE,
        DEVICE_MODULE_KIND_SYSTEM_PACKAGE,
        description_code=SERVICES_DESCRIPTION_CONTAINER,
    ),
    _row(
        DEVICE_HERMES_WEBUI_MODULE,
        DEVICE_MODULE_KIND_CONTAINER,
        sealed_fields=(
            SealedField(
                key=DEVICE_HERMES_WEBUI_SECRET_KEY,
                opened_key="secret",
                aad=DEVICE_HERMES_WEBUI_SECRET_AAD,
                secret_bytes=DEVICE_HERMES_WEBUI_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_HERMES_WEBUI_PASSWORD_KEY,
                opened_key="password",
                aad=DEVICE_HERMES_WEBUI_PASSWORD_AAD,
                secret_bytes=DEVICE_HERMES_WEBUI_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
        entry_title=SERVICES_HERMES_WEBUI_TITLE,
        has_forwarder=True,
        token_field=DEVICE_HERMES_WEBUI_SECRET_KEY,
        is_token_minted=True,
        is_gateway_used=True,
    ),
    _row(
        DEVICE_AYAKALEAF_MODULE,
        DEVICE_MODULE_KIND_CONTAINER,
        sealed_fields=(
            SealedField(
                key=DEVICE_AYAKALEAF_SECRET_KEY,
                opened_key="secret",
                aad=DEVICE_AYAKALEAF_SECRET_AAD,
                secret_bytes=DEVICE_AYAKALEAF_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_AYAKALEAF_PASSWORD_KEY,
                opened_key="password",
                aad=DEVICE_AYAKALEAF_PASSWORD_AAD,
                secret_bytes=DEVICE_AYAKALEAF_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_AYAKALEAF_SESSION_SECRET_KEY,
                opened_key="session_secret",
                aad=DEVICE_AYAKALEAF_SESSION_SECRET_AAD,
                secret_bytes=DEVICE_AYAKALEAF_SECRET_BYTES,
            ),
            SealedField(
                key=DEVICE_AYAKALEAF_INVITE_SECRET_KEY,
                opened_key="invite_secret",
                aad=DEVICE_AYAKALEAF_INVITE_SECRET_AAD,
                secret_bytes=DEVICE_AYAKALEAF_SECRET_BYTES,
            ),
        ),
        description_code=SERVICES_DESCRIPTION_AYAKALEAF_MODULE,
        entry_title=SERVICES_AYAKALEAF_TITLE,
        has_forwarder=True,
        token_field=DEVICE_AYAKALEAF_SECRET_KEY,
        is_token_minted=True,
        is_gateway_used=True,
    ),
)
_ROWS_BY_NAME = {row.name: row for row in DEVICE_MODULE_ROWS}


def module_row(name: str) -> DeviceModuleRow:
    """The row describing one module.

    Args:
        name: The manifest name.

    Returns:
        The row.

    Raises:
        KeyError: For a name the table does not hold.
    """
    return _ROWS_BY_NAME[name]


def rows_of_kind(kind: str) -> tuple:
    """Every row of one kind, in the table's order.

    Args:
        kind: One of ``DEVICE_MODULE_KIND_*``.

    Returns:
        The rows.
    """
    return tuple(row for row in DEVICE_MODULE_ROWS if row.kind == kind)


def account_layer_rows() -> tuple:
    """Every row of the account layer, in the table's order.

    Returns:
        The rows.
    """
    return tuple(row for row in DEVICE_MODULE_ROWS if row.is_account_layer)


def account_layer_names() -> tuple:
    """The names of the account-layer modules, in the table's order.

    Returns:
        The names.
    """
    return tuple(row.name for row in account_layer_rows())


def account_program_rows() -> tuple:
    """Every row of a program run as a person's account, in the table's order.

    Returns:
        The rows.
    """
    return rows_of_kind(DEVICE_MODULE_KIND_ACCOUNT_PROGRAM)


def gateway_module_names() -> tuple:
    """The names of the modules that call the AI gateway, in the table's order.

    Returns:
        The names.
    """
    return tuple(row.name for row in DEVICE_MODULE_ROWS if row.is_gateway_used)


def gateway_container_names() -> tuple:
    """The names of the container modules whose containers call the AI gateway, in the table's order.

    Returns:
        The names.
    """
    return tuple(
        row.name
        for row in DEVICE_MODULE_ROWS
        if row.is_gateway_used and row.kind == DEVICE_MODULE_KIND_CONTAINER
    )


def gateway_instance_names() -> tuple:
    """The names of the programs run as an account that hold one gateway key per enabled account.

    Returns:
        The names.
    """
    return tuple(
        row.name
        for row in DEVICE_MODULE_ROWS
        if row.is_gateway_used and row.kind == DEVICE_MODULE_KIND_ACCOUNT_PROGRAM
    )


def account_program_names() -> tuple:
    """The names of the programs run as a person's account, in the table's order.

    Returns:
        The names.
    """
    return tuple(row.name for row in account_program_rows())
