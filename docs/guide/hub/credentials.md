---
title: Credentials
---

# Credentials

The **Credentials** page stores SSH keys, logins and tokens in the hub's vault, once each. Every page that signs in somewhere picks a stored entry from a list.

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

Paste the whole private key, with its BEGIN and END lines. The hub rejects a public key with `key_is_public`, and an encrypted key without its passphrase with `key_passphrase_needed`. After saving, the page shows the name, the date added and where the entry is used; the value is not shown again. To change a value, delete the entry and add it again.

## Who uses them

| Where                                   | Kind it picks                                 |
| --------------------------------------- | --------------------------------------------- |
| **Install agent** on **Devices**        | an SSH key or a login, and a login for `sudo` |
| A VS Code instance on a Windows machine | the Windows login of the account it runs as   |
| A provider on **AI**                    | a token, as the provider's API key            |
| An exit node on **Proxy**               | a token, where the node's link has one        |

A VS Code instance on Windows needs the account's login because Windows starts the instance with that username and password. When Windows rejects the login, the instance reports `credential_invalid`; update the stored login and apply again. Setting up the instance is on [VS Code](../agent/modules/vscode.md).

Each row counts its users, as **2 devices** or **1 provider**, and **Delete** opens a confirmation with the same count. A device or a provider that loses its entry needs a new one, and an exit node that loses its token is disabled.

## The vault

Every value is in `config/credentials/vault.json`. One data key encrypts the values together with their names and kinds. The data key is stored wrapped under the master passphrase you set during `nhub setup`. A backup of `config/` holds only ciphertext, and restoring it requires the passphrase it was taken under.

The box keeps a working copy of the data key outside `config/`, so the hub reads the vault without the passphrase. Without that copy the vault is locked, and anything that needs a stored entry returns `vault_locked`.

## Change the passphrase

Run the rekey command on the hub box, and type the new passphrase twice:

```bash
sudo nhub vault rekey
```

The command wraps the same data key under the new passphrase, and nothing sealed is encrypted again. `--stdin` reads the new passphrase from standard input. A backup taken before the rekey still opens with the passphrase it was taken under.

## A lost passphrase

The running box reads the vault with its working copy of the data key. `sudo nhub vault rekey` therefore sets a new passphrase even when the old one is lost. Back up `config/` again after the rekey.

::: warning
A backup opens only with the passphrase it was taken under. With that passphrase lost, the keys, logins and tokens in that backup are gone, and each one is entered again on the restored box.
:::
