# nhub command

`nhub` is the command-line tool of Neutrino Hub, installed with the hub's package. When the panel does not open, you can repair the hub with it from a terminal on the hub's computer.

Run the following commands on the computer that runs the hub. On Linux and macOS, put `sudo` before a command that needs administrator rights. On Windows, open a terminal as administrator and leave out `sudo`. Without enough rights, a command prints the line to run.

Every command level takes `-h` and prints its help in English.

## Common commands

`nhub status` shows whether each service is running, and it works without administrator rights. On Linux it prints one line per service: `running, enabled` means the service runs and starts at boot, and `not installed` means the feature was never turned on. On macOS and Windows it prints a single line.

```bash
nhub status
```

```text
  xray: running, enabled
  router: running, enabled
  transport: running, enabled
  dnsmasq: running, enabled
  web: running, enabled
  cliproxyapi: running, enabled
  netbird: stopped, disabled
  easytier: stopped, disabled
  relay: not installed
  sakurafrp: not installed
  openfrp: not installed
```

The service behind each line is in [Service names](#service-names).

For a forgotten panel address, the following command prints the address without opening a browser. With `sudo`, it prints the configured address and the setup token. Without `sudo`, it prints one more line with a hint.

```bash
nhub open --print
```

```text
http://192.168.1.20:8080/
for the panel's configured address and the setup token, run: sudo nhub open --print
```

`sudo nhub reset password` replaces a forgotten panel password. It shows a confirmation prompt first, and after the answer `y` it reads the new password. Every session is signed out, and every other setting stays as it was.

When repeated wrong passwords lock the panel, `sudo nhub unlock` lifts the panel's sign-in lock and the SSH ban.

## All commands

The order matches `nhub -h`:

| Command               | Effect                                                                                                              | Options                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `nhub setup`          | Sets up this system for the first time, and runs one time only. The wizard in the browser usually does this instead | `--stdin`, `--json <file>`: read one JSON file as every answer                        |
| `nhub run`            | Runs one process in the foreground. Only the service manager calls it                                               | `--only-<name>`                                                                       |
| `nhub open`           | Opens the panel in the browser, or the wizard before setup                                                          | `--print`: print the address only                                                     |
| `nhub start`          | Starts every enabled service                                                                                        | `--yes`, `--only-<name>`, `--interface <interface>`                                   |
| `nhub stop`           | Stops the hub's services, which start again at the next boot                                                        | `--yes`, `--only-<name>`, `--interface <interface>`                                   |
| `nhub status`         | Shows whether each service is running                                                                               | None                                                                                  |
| `nhub service run`    | The entry point that only the Windows service manager calls                                                         | None                                                                                  |
| `nhub apply`          | Renders every configuration from `config/` again, validates it, then applies it                                     | `--dry-run`: render and validate only, apply nothing. `--skip-apply`, `--only <part>` |
| `nhub unlock`         | Lifts the panel's sign-in lock and the SSH ban                                                                      | None                                                                                  |
| `nhub reset <target>` | Returns one part to its state right after install. The targets are in the next section                              | `--yes`, `--stdin`                                                                    |
| `nhub update`         | Installs the latest release, and restores the old version when the new one does not respond                         | `--yes`, `--package <file>`: install this file                                        |
| `nhub vault rekey`    | Changes the vault passphrase. Old backups still use the old passphrase                                              | `--stdin`                                                                             |
| `nhub scan-secrets`   | For developers: checks for keys before a commit                                                                     | `--staged`, `--history`, `--no-entropy`, `--no-vendor`, `--quiet`                     |

The global options are `--version` and `--dev`:

- `--version` prints the version.
- `--dev` goes before the subcommand and runs the hub from a source checkout.

## Reset targets

Without a target, `sudo nhub reset` lists what it can reset and changes nothing. It prints the following and exits with 2:

```bash
sudo nhub reset
```

```text
nhub reset <target>, where target is one of:

  all       every module's config, the panel password, and the keys and tokens this box collected; stops the hub's services too
  network   hands the machine's network back (the firewall, the engines, the resolver) and changes no config; removing the package runs it
  password  the panel password, leaving every other setting alone

Nothing was reset.
```

| Target     | Effect                                                                                                           | Next step                                           |
| ---------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `password` | Changes the panel password and signs everyone out. With `--stdin`, it reads the new password from standard input | Sign in with the new password                       |
| `network`  | Hands this system's network back to the system without changing any config. The panel stops                      | Run `sudo nhub start` after the network works again |
| `all`      | Resets every config to the examples, clears the password and the keys, and stops the services                    | Run `sudo nhub setup`, or complete the wizard again |

After `nhub reset all`, every agent and client must join again with a new link, because the hub key changes.

## Service names

`--only-<name>` starts or stops one service, for example `sudo nhub stop --only-web`. The option is available on Linux only. `nhub status` uses the same names.

| Name                   | Meaning                                                    |
| ---------------------- | ---------------------------------------------------------- |
| `web`                  | The panel                                                  |
| `transport`            | The connection port, which clients and agents connect to   |
| `relay`                | The SSH relay                                              |
| `sakurafrp`, `openfrp` | The frpc of SakuraFrp and of OpenFrp                       |
| `cliproxyapi`          | The AI gateway                                             |
| `dnsmasq`, `router`    | DNS and routing                                            |
| `xray`                 | The exit program                                           |
| `supplicant`, `dhcpcd` | Run per interface, and also take `--interface <interface>` |

`nhub apply --only` takes `router`, `dnsmasq`, `cliproxyapi`, `overlay`, `transport` or `xray`.

## Rights, confirmation and exit codes

Every command except `nhub status`, `nhub run` and `nhub scan-secrets` needs administrator rights. `nhub open` is an exception while the panel is running: it then works without administrator rights, and so does `nhub open --print`.

`nhub start`, `nhub stop`, `nhub reset <target>` and `nhub update` show `[y/N]` and act only after the answer `y`. `--yes` skips the prompt. Without a terminal and without `--yes`, the command changes nothing, so a script must pass `--yes`.

| Exit code | Meaning                               |
| --------- | ------------------------------------- |
| 0         | Done                                  |
| 1         | The answer was no, or a step failed   |
| 2         | Not enough rights, or no target given |
| 130       | Ctrl-C was pressed                    |
