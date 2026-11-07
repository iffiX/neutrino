# nclient command

`nclient` is the client's command-line program, and every action of the client window is also available through it in a terminal or a script. It installs with the client, and the phone apps have no `nclient`. It runs as your own account; with `sudo`, it returns `root_refused`.

Every command except `nclient gui` needs the client to be running. Otherwise the command exits with 1 and returns `client_not_running`, and `nclient gui` opens the client. Help and messages use the client's language. The following outputs come from real runs, on a system named `my-computer`.

Each command level prints its help with `-h`, for example:

```bash
nclient hub -h
```

```text
Usage: nclient hub <command> [arguments]

The hubs you joined.

  list         each hub's connection and the way it is reached
  join         join a hub with a link
  leave        leave a hub
  open         open the hub's panel in the browser, through a forward

Example: nclient hub join "neutrino://…"
```

## Global options

These options go before the subcommand.

| Option         | Effect                                                                                |
| -------------- | ------------------------------------------------------------------------------------- |
| `-h`, `--help` | Shows the help of this level                                                          |
| `--version`    | Prints the client's version                                                           |
| `--hub <hub>`  | With several hubs joined, names the hub this command acts on. Not needed with one hub |

## The client itself

| Command        | Effect                                                                                                     |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `nclient gui`  | Runs the client and opens its window, or brings the window to the front when the client is already running |
| `nclient quit` | Closes the window, closes every forward and unmounts every share                                           |

## hub: hubs

`nclient hub list` prints one line per hub with its number, name, connection state, connection method and round-trip time.

```bash
nclient hub list
```

```text
1  my-computer  Connected · LAN · 0 ms
```

The connection methods are LAN, NetBird, EasyTier, SSH relay, Direct, SakuraFrp and OpenFrp.

| Command                           | Effect                                                                                                            |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `nclient hub list`                | Lists each hub and its state                                                                                      |
| `nclient hub join '<link>'`       | Joins with a link made by **New client link** in the panel. A link works one time and stays valid for 30 minutes  |
| `nclient hub leave <hub> [--yes]` | Closes the forwards, unmounts the shares, leaves the virtual network and deletes the binding. Shows `[y/N]` first |
| `nclient hub open <hub>`          | Opens the panel in the browser. This client needs the panel permission                                            |

`<hub>` is the hub's name or its number in `nclient hub list`. For a wrong value, the command lists the hubs available:

```bash
nclient hub leave 9
```

```text
no hub named 9; there are: my-computer
```

## app: apps

`nclient app list` shows the apps. Under each system, it prints one line per app with its source and whether it is in use. Under each app, it prints one line per entry with its local address.

```bash
nclient app list
```

```text
my-computer
  whoami  declared  not in use
    8088  web  http://whoami.my-computer.localhost:24110/
```

`use` opens a forward for each entry of an app and prints the local address. That address goes into a browser or into your program.

```bash
nclient app use whoami
```

```text
forwarding http://whoami.my-computer.localhost:24110/
```

`stop` ends the use of the app.

```bash
nclient app stop whoami
```

```text
stopped whoami
```

While an app is not in use, `open` cannot open it and the command exits with 1.

```bash
nclient app open whoami
```

```text
use the app first: nclient app use
```

| Command                                       | Effect                                                                                              |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `nclient app list`                            | Lists apps by system, with source, entries, local addresses and whether each is in use              |
| `nclient app use <app>`                       | Opens a forward for each entry and prints the local addresses                                       |
| `nclient app open <app>`                      | Opens the first web entry in the browser                                                            |
| `nclient app stop <app>`                      | Closes this app's forwards                                                                          |
| `nclient app set <app> --port <entry>=<port>` | Fixes the local port of one entry, and repeats for more entries. An empty port restores the default |

When two systems have apps with the same name, the app is written as `<system>/<app>`.

A web entry's address is `<app>.<system>.localhost:<port>`, and `127.0.0.1:<port>` on macOS. A port entry's address is `127.0.0.1:<port>`. The port is between 24000 and 31999 and stays the same after its first assignment.

## ssh

`nclient ssh list` lists the systems with SSH turned on and their enabled accounts. The first account is the default, and the local address follows the accounts.

```bash
nclient ssh list
```

```text
my-computer  lab 127.0.0.1:26261
```

| Command                                                | Effect                                                                                                                |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `nclient ssh list`                                     | Lists systems, accounts and local addresses                                                                           |
| `nclient ssh open [<account>@]<system> [-- <command>]` | Signs in to a system. With `--`, runs only that command and keeps its exit code                                       |
| `nclient ssh config show`                              | Prints the path and content of `~/.ssh/neutrino_config`                                                               |
| `nclient ssh config install`                           | Adds an `Include` line at the top of `~/.ssh/config`. After that, ssh, scp and VS Code can use `<system>.nt` directly |
| `nclient ssh config uninstall`                         | Removes that `Include` line and keeps the configuration file of Neutrino Hub                                          |
| `nclient ssh proxy`                                    | Called by `ProxyCommand` only                                                                                         |

[SSH connections](/en/access/ssh) shows how to connect with these programs.

## terminal: terminals

`exec` runs one command and returns immediately. It passes input, output and the exit code through unchanged, so it fits into scripts.

```bash
nclient terminal exec my-computer -- uname -sr
```

```text
Linux 5.15.0-198-generic
```

| Command                                       | Effect                                                                        |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| `nclient terminal list <system>`              | Lists the sessions on a system                                                |
| `nclient terminal open <system>`              | Opens a new shell, which ends when the shell exits                            |
| `nclient terminal attach <system> <session>`  | Attaches to a running session. Ctrl+] detaches, and the session keeps running |
| `nclient terminal exec <system> -- <command>` | Runs one command                                                              |
| `nclient terminal set <system> <session>`     | Changes a session: `--persist on\|off`, `--share on\|off`                     |
| `nclient terminal stop <system> <session>`    | Ends the session and the programs in it                                       |

`--account` picks an enabled account and defaults to the first one; `open` and `exec` both take it. With `--tty`, `exec` gives the command a terminal, which htop and vim need.

`exec` returns the remote command's exit code. 125 means the request was refused, and 126 means no hub offers this system. For a wrong system name, it shows **no machine named lab-gpu; there are: my-computer** and returns 126.

## file: files

| Command                                   | Effect                                                                                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `nclient file list`                       | Lists the shares by system: share name, local mount location, mount state                                                 |
| `nclient file mount <system>[/<share>]`   | Mounts without a password. The default location is `~/remote/<system>-<share>`, or the first free drive letter on Windows |
| `nclient file unmount <system>[/<share>]` | Unmounts. When a folder share is mounted for several accounts, `--account` names one                                      |

`nclient file mount` also takes these options: `--account` picks the account, `--path` picks the folder (Linux, macOS), and `--drive` picks the drive letter (Windows).

## ai

| Command           | Effect                                                                              |
| ----------------- | ----------------------------------------------------------------------------------- |
| `nclient ai show` | Shows which gateway claude, codex and gemini on this computer point at              |
| `nclient ai set`  | Writes the hub's AI gateway into their configuration. Running it again refreshes it |

```bash
nclient ai show
```

```text
claude  -  its own
codex   -  its own
gemini  -  its own
```

A computer with the agent installed takes these settings from its system's page in the panel, and these two commands are not used there. See [AI gateway](/en/hub/ai_gateway). On such a computer, `nclient ai show` prints one more line: **This is a managed device: set its AI tools on the hub's panel, on its machine page.**

## rdp: remote desktop

| Command                        | Effect                                                                                   |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| `nclient rdp list`             | Lists the systems that share a desktop: the user at the screen and the number of viewers |
| `nclient rdp connect <system>` | Opens the viewer. The client gets the password automatically                             |

## settings: settings

`nclient settings show` prints one line per setting with its name, current value and allowed values.

```bash
nclient settings show
```

```text
language     en  en, zh-CN
theme        system  system, dark, light
ssh_include  off  on, off
```

`nclient settings set <setting> <value>` changes one setting, for example `nclient settings set theme dark`. `ssh_include` is **SSH programs reach the machines** on the client's **Settings** page.

## Rights and confirmation

A computer runs the client of one account at a time. While the client of another account runs on this computer, commands return `client_held`.

Only `nclient hub leave` shows `[y/N]` first. Every other command runs immediately.
