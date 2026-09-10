"""Sealing node secrets into the vault, and opening them for a render.

``nodes.json`` holds ``secret_id`` references; the material — a Shadowsocks
password or a VLESS user id — lives sealed as a ``token`` object. Importing a
share link seals here, and rendering resolves here: the resolution helpers
read the vault and touch nothing else, so the renderer itself stays pure.
"""

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.credentials.vault import SecretVault
from neutrino_hub.modules.xray.node_config import XrayNodeConfig, XrayNodeList


def store_node_secret(node: XrayNodeConfig, vault: SecretVault | None = None) -> None:
    """Seal a freshly parsed node's material and reference it.

    Args:
        node: The node, carrying its raw material in memory.
        vault: The vault to seal into; a fresh one when not given.

    Raises:
        VaultLockedError: If there is no data key on this box.
        ValueError: If the node carries no material to seal.
    """
    vault = vault or SecretVault()
    value = node.password if node.protocol == "shadowsocks" else node.uuid
    if not value:
        raise ValueError(f"node {node.id!r} carries no secret to seal")
    if node.secret_id and vault.get(node.secret_id) is not None:
        vault.replace(node.secret_id, secret={"value": value})
        return
    node.secret_id = vault.add(
        kind="token",
        name=f"node {node.name or node.id}",
        secret={"value": value},
    ).id


def resolve_node_secrets(
    node_list: XrayNodeList, vault: SecretVault | None = None
) -> None:
    """Open every referenced node secret into memory, for a render.

    A dangling reference — or a locked vault, which dangles every one —
    leaves the node without material, and the renderer excludes it the way
    it excludes a disabled node.

    Args:
        node_list: The parsed list; its nodes are given their material.
        vault: The vault to read; a fresh one when not given.
    """
    vault = vault or SecretVault()
    for node in node_list.nodes:
        if not node.secret_id or node.has_secret_material:
            continue
        try:
            value = vault.open(node.secret_id).get("value", "")
        except VaultLockedError:
            return
        except ValueError:
            continue
        if node.protocol == "shadowsocks":
            node.password = value
        else:
            node.uuid = value


def delete_node_secret(node: XrayNodeConfig, vault: SecretVault | None = None) -> None:
    """Remove the vault object a node references, if it still exists.

    Args:
        node: The node being deleted.
        vault: The vault to delete from; a fresh one when not given.
    """
    if not node.secret_id:
        return
    try:
        (vault or SecretVault()).delete(node.secret_id)
    except ValueError:
        # An object already gone leaves the node deletable.
        pass
