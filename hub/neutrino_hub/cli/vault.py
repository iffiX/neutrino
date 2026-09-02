"""Maintain the credential vault.

    nhub vault rekey

Rekey re-encrypts every stored secret under a fresh master key.
"""

import argparse
import sys

from neutrino_hub.modules.credentials.vault import SecretVault, VaultError


def main() -> int:
    """Run one vault action.

    Returns:
        Process exit status: 0 on success, 1 when the vault refuses.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    actions.add_parser("rekey", help="Re-encrypt every secret under a fresh master key")
    parser.parse_args()

    try:
        count = SecretVault().rekey()
    except VaultError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"rekeyed: every secret is sealed under a fresh master key ({count} stored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
