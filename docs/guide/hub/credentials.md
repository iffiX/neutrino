---
title: Credentials
---

# Credentials

The **Credentials** page stores SSH keys, logins and tokens in the hub's vault, each one time. A page that signs in somewhere picks a stored entry from a list.

![The Credentials page with SSH keys, logins and tokens](/guide/en/credentials.webp)

## Keys, logins and tokens

| Section      | What an entry holds                                         | Added with    |
| ------------ | ----------------------------------------------------------- | ------------- |
| **SSH keys** | a private key, and its passphrase when the key is encrypted | **Add key**   |
| **Logins**   | a username and password pair, or a bare password            | **Add login** |
| **Tokens**   | one secret value under a name                               | **Add token** |

To add an entry:

1. Select **Add key**, **Add login** or **Add token**.
1. Fill **Name** and the value: **Private key**, **Username** and **Password**, or **Value**.
1. If the key is encrypted, fill **Key passphrase**.
1. Select **Save key**, **Save login** or **Save token**.

Paste the whole private key, with its BEGIN and END lines. The hub rejects a public key with `key_is_public`, and an encrypted key without its passphrase with `key_passphrase_needed`. After saving, the page shows the name, the date added and where the entry is used, and the value is not shown again. To change a value, delete the entry and add it again.

## Who uses them

| Where                                               | Kind it picks                                 |
| --------------------------------------------------- | --------------------------------------------- |
| **Install agent** on the **Devices** page           | an SSH key or a login, and a login for `sudo` |
| **SSH Relay** on the **Access** page                | an SSH key or a login                         |
| A VS Code or CloudCLI instance on a Windows machine | the Windows login of the account it runs as   |
| A provider on the **AI** page                       | a token, as the provider's API key            |
| An exit node on the **Proxy** page                  | a token, where the node's link has one        |

Windows starts an instance with its account's username and password, so a VS Code or CloudCLI instance there needs the account's login. The machine's AI tools on Windows run as the same account and use the same login. When Windows rejects the login, the module reports `credential_invalid`; update the stored login and apply the module again.

Each row counts its users, as **2 devices** or **1 provider**, and **Delete** opens a confirmation with the same count. A device or a provider that loses its entry needs a new one. An exit node that loses its token is disabled, and the SSH Relay stops.

## The vault

Every value is in `config/credentials/vault.json`. One data key encrypts the values together with their names and kinds. The data key is stored wrapped under the master passphrase you set during `nhub setup`, so a backup of `config/` holds only ciphertext.

The box keeps a working copy of the data key outside `config/`, so the hub reads the vault without the passphrase. Without that copy the vault is locked, and anything that needs a stored entry returns `vault_locked`.

## Change the passphrase

On the hub box, run the rekey command and type the new passphrase twice:

```bash
sudo nhub vault rekey
```

The command wraps the same data key under the new passphrase, and no stored value is encrypted again. `--stdin` reads the new passphrase from standard input. A backup taken before the rekey still opens with the passphrase it was taken under.

## A lost passphrase

The running box reads the vault with its working copy of the data key. `sudo nhub vault rekey` therefore sets a new passphrase even when the old one is lost. Take a new backup of `config/` after the rekey.

::: warning
A backup opens only with the passphrase it was taken under. With that passphrase lost, the keys, logins and tokens in that backup are gone, and each one is entered again on the restored box.
:::
