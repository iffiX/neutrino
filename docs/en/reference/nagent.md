# nagent command

`nagent` is the agent's own command, with the same name on Linux, Windows and macOS. When a system cannot connect to the hub, you can use it on that system to find the cause and join again.

Run the following commands on the system where the agent is installed. On Linux and macOS, put `sudo` in front. On Windows, open an administrator terminal and leave out `sudo`. Without enough rights, a command prints the reason and the line to run, then exits with 2:

```bash
nagent status
```

```text
nagent status needs root (it asks the agent over its root-only control socket):
    sudo nagent status
```

## Check the status

When the system cannot connect to the hub, start with `sudo nagent status`. A healthy agent prints the following and exits with 0:

```bash
sudo nagent status
```

```text
neutrino-agent 0.6.0
hub        tcp://192.168.1.20:8443
binding    486e750d56454a11b1e71d7179789450
service    running
heartbeat  ok. The service holds its session to the hub
```

Each line means:

| Line        | Meaning                                         |
| ----------- | ----------------------------------------------- |
| First line  | The agent's version                             |
| `hub`       | The address of the hub this system joined       |
| `binding`   | This system's ID on the hub                     |
| `service`   | Whether the agent's service is running          |
| `heartbeat` | The connection to the hub; `ok` means connected |

When something is wrong, the command exits with 1. The output then shows that the system has joined no hub, that the service is not running, or that the hub cannot be reached. In the last case, the `heartbeat` line shows one of the following codes. [Troubleshooting](/en/reference/troubleshooting) has the detailed steps.

| Code                    | Meaning                                                                                    | Fix                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `hub_untrusted`         | The hub's key does not match, usually because the hub was reset or reinstalled             | Generate a new link in the panel and run `sudo nagent join`                                |
| `hub_key_missing`       | This binding comes from 0.5                                                                | Run `sudo nagent join` with a new link. See [Upgrade from 0.5](/en/hub/upgrade)            |
| `binding_unknown`       | The hub has no record of this system, usually because **Forget** was selected in the panel | Run `sudo nagent join` with a new link                                                     |
| `replaced`              | Another session holds this binding                                                         | Restart the service, or join with a new link                                               |
| `hub_unreachable`       | The hub cannot be reached                                                                  | Check the network from this system to the hub. The firewall must allow the connection port |
| `protocol_too_old`      | The agent is too old                                                                       | Select **Update agent** on the system's page                                               |
| `protocol_too_new`      | The hub is too old                                                                         | Update the hub first                                                                       |
| `control_unavailable`   | The hub is busy and did not respond                                                        | Wait. The agent reconnects automatically                                                   |
| `transport_unavailable` | The agent's transport program is missing or damaged                                        | Reinstall the agent                                                                        |

## Join and leave

To join this system to a hub, open the **Agents** page in the panel and select **Add by link** to generate a link. Then run the following command, with `<link>` replaced by that link inside single quotes:

```bash
sudo nagent join '<link>'
```

Without a link, the command prompts for one to paste. After joining, the system returns to its old row in the panel, with its name and settings kept.

If this system already joined another hub, the command shows `this machine is bound to ...; replace it? [y/N]`. The answer `y` replaces the old hub with the new one, and `--yes` skips the prompt.

`sudo nagent leave` leaves the hub. It deletes the binding and keeps the agent and its service. Without a binding, it exits with 1.

## All commands

The order matches `nagent -h`:

| Command                    | Effect                                                                                                   | Options                              |
| -------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `nagent join [<link>]`     | Joins the hub the link names                                                                             | `--yes`: replace an existing binding |
| `nagent leave`             | Leaves the hub and deletes the binding, keeping the agent and its service                                | `--yes`                              |
| `nagent status`            | Prints the version, the bound hub, the service and the connection                                        | None                                 |
| `nagent sync`              | Sends a report to the hub immediately. Exits with 1 when the service is not running or no binding exists | None                                 |
| `nagent start`             | Starts the agent's service                                                                               | `--yes`                              |
| `nagent stop`              | Stops the service and keeps the binding. The service starts again at the next boot                       | `--yes`                              |
| `nagent run`               | Runs in the foreground. Only systemd and the macOS LaunchDaemon call it                                  | None                                 |
| `nagent service run`       | The entry point that only the Windows service manager calls                                              | None                                 |
| `nagent service uninstall` | Removes the services, scheduled tasks and firewall rules that the agent and its apps added               | `--yes`                              |
| `nagent answer`            | Called by the agent only                                                                                 | `--prompt`, `--answer`               |
| `nagent step-down`         | Called by the agent only                                                                                 | `--uid`, `--gid`                     |

`nagent service uninstall` keeps shares, accounts and app data. Removing the package runs it automatically, and an upgrade does not run it. macOS has no uninstaller, so on macOS the command also removes the agent. See [Uninstall](/en/hub/uninstall).

## Rights, confirmation and exit codes

Every command except `--version`, `nagent answer` and `nagent step-down` needs administrator rights.

`nagent leave`, `nagent start`, `nagent stop` and `nagent service uninstall` show `[y/N]` first, and `--yes` skips it. `nagent join` shows it only when the system is already bound to a hub. Without a terminal and without `--yes`, a command prints one line of explanation and changes nothing.

Without a subcommand, or with `nagent service` and no action, the command prints its help and exits with 2.
