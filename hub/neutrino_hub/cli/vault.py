"""Maintain the credential vault.

    nhub vault rekey
    printf '%s' "$NEW_PASSPHRASE" | nhub vault rekey --stdin

Rekey wraps the vault's data key under a new master passphrase. Nothing
sealed is re-encrypted: the data key does not change, only what opens it.
"""

import argparse
import sys

from neutrino_hub.cli.password import PasswordRefused, read_new_password
from neutrino_hub.modules.credentials.vault import SecretVault, VaultError
from neutrino_hub.utils.passwords import PASSWORDS_MASTER_RULES


def main() -> int:
    """Run one vault action.

    Returns:
        Process exit status: 0 on success, 1 when the vault refuses.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    rekey = actions.add_parser(
        "rekey", help="Wrap the data key under a new master passphrase"
    )
    rekey.add_argument(
        "--stdin",
        action="store_true",
        help="read the new passphrase from standard input rather than prompting",
    )
    arguments = parser.parse_args()

    try:
        passphrase = read_new_password(
            is_stdin=arguments.stdin,
            prompt="New vault passphrase",
            rules=PASSWORDS_MASTER_RULES,
        )
        SecretVault().change_passphrase(passphrase)
    except (PasswordRefused, VaultError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print("rekeyed: the vault now opens with the new passphrase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
