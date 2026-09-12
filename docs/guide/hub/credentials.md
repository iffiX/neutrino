---
title: Credentials
---

# Credentials

SSH keys, logins and tokens are written once on the **Credentials** page and read by the pages that sign in with them. This page covers what the **Credentials** page holds, how the vault seals it, and what a lost passphrase costs.

## SSH keys, logins and tokens

| Kind         | What it holds                                               | Added with                                                     |
| ------------ | ----------------------------------------------------------- | -------------------------------------------------------------- |
| **SSH keys** | a private key, and its passphrase when the key is encrypted | **Add key**, the whole key pasted with its BEGIN and END lines |
| **Logins**   | a username and password pair, or a bare password            | **Add login**                                                  |
| **Tokens**   | a single secret value under a name                          | **Add token**                                                  |

![The Credentials page with keys, logins and tokens](/guide/en/credentials.webp)

Every entry is write-only: the page shows names and kinds, and a value is never shown again after it is saved. The hub rejects a public key with `key_is_public`, because it needs the matching private key. It rejects an encrypted key without its passphrase with `key_passphrase_needed`.

## Who uses them

You pick a credential on the page that signs in with it. **Install agent** on [the Devices page](./devices.md) picks an SSH key or a login for the machine, and a login for `sudo` there. A provider on [the AI page](./ai.md) is keyed with a token, and a proxy node with a token where its link has one. The delete confirmation counts what loses the entry. A device or a provider that loses its credential needs a new one, and a node that loses its token is disabled.

## The vault

The vault is the file under `config/` that holds every value. A data key encrypts the values together with their names and kinds. The data key is itself sealed under the master passphrase set on the wizard's second screen. A backup of `config/` therefore holds ciphertext, and a restore of it requires the same passphrase.

## Rekey and a lost passphrase

`sudo nhub vault rekey` wraps the data key under a new passphrase, and nothing sealed is re-encrypted. An archive downloaded before the rekey still opens with the passphrase it was taken under.

::: danger
The passphrase is the one key to the vault. A lost passphrase means the vault's contents are gone, and every credential and AI account is entered again.
:::
