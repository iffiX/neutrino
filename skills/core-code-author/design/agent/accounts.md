# A machine's accounts

An available account is one of a managed machine's own accounts that the
person added on its machine page, with what the account layer needs to know
of it. The default account is the one available account that every module
serving accounts always enables, chosen once per machine and never changed
while the system still has it.

## Available accounts

The hub keeps them per machine in `config/devices/<id>/accounts.json`,
`{default_account, accounts: [{account, login_id, share_path, shell_path,
is_ai_tools_enabled, tool_configs}]}`:

| Field | Holds |
| --- | --- |
| `default_account` | the machine's default account, one of `accounts`; empty while the machine has none ("The default account") |
| `account` | an account the machine reports in its `machine` section |
| `login_id` | on Windows, the vault login that holds the account's password, which the form asks once; empty elsewhere |
| `share_path` | the folder the account's share serves, absolute in the machine's own form; empty is the account's home |
| `shell_path` | the shell the account's terminal and SSH server start, absolute; empty is the account's login shell, and PowerShell on Windows |
| `is_ai_tools_enabled` | whether the account's AI tools use the hub's AI gateway ([ai_tools.md](ai_tools.md)); false on a new account |
| `tool_configs` | the account's model choices, `{claude: {default, opus, sonnet, haiku}, codex: {model, model_reasoning_effort}, gemini: {model}, opencode: {model}}`, each empty for the gateway's default |

A module of the account layer keeps its enabled accounts in its own file
under `config/devices/<id>/`, each one an available account, the default
first, and runs one instance for each.

| Rule | Reason |
| --- | --- |
| The machine reports the accounts that can log in and have their home: on Linux and macOS an account with a login shell and a home that exists, on Windows an account that signed in at least once and so has a profile ([../agent.md](../agent.md), "The platform layer"). Every list of a machine's accounts offers these alone: the setup's picker and the form's **System account** picker, which leaves out the accounts already available. | A module run as an account needs the account's home. The agent makes no profile and no home for an account, so an account becomes usable once the person signed in as it. |
| A module of the account layer with no enabled account runs as a service with no instance: **Start** takes and the module reads `running`, and **Stop** reads `stopped`. An account enabled while it runs starts that one instance. | A module installed is a service, whatever instances it has. |
| The machine reports `account_details` in its `machine` section beside `accounts`, one `{account, home, shell}` for each, `home` in the machine's own form and `shell` the login shell, empty on Windows. | The form shows each default before the person changes it. |
| Every feature that runs as an account reads that account's row: the file share its `share_path`, the terminal and the SSH server its `shell_path`, every program its login on Windows. | One form per account holds it, so no module asks again and two modules never disagree. |
| On Windows the account's password is the one login every feature of the account signs in with: the scheduled tasks of the programs and of the SSH server, the terminal's logon, Containers' Podman machine, and the AI tools' one-shot tasks. A changed password is a new login; the old one is deleted ([../ui_behavior.md](../ui_behavior.md), "Secrets"). | Windows starts a process as another account only with its password, and one password per account is the one a person can keep up to date. |
| A terminal and a command run as an enabled account of the Terminal module, never as root or SYSTEM. With no account enabled, the module opens no shell. | A shell the hub opens is a person's own; root's work is the agent's alone. |
| The file share serves one Home share per enabled account, named after the account, at its `share_path`, and the folder shares the person names, each open to the enabled accounts checked for it; every enabled account has one SMB user, whose password the hub generates and seals ([../agent.md](../agent.md), "The file share's accounts", [modules/file_share.md](modules/file_share.md)). | The person mounts without a password, and a client holds a password that opens only the shares of that account. |
| Removing an available account takes it out of every module's enabled accounts, switches its AI tools back, and deletes its login and the generated passwords of its features, in one write; on Windows the agent switches the tools back with the login it kept from the switch ([ai_tools.md](ai_tools.md)). The default account is never removed: `account/remove` rejects it with `account_is_default {account}`. | A module never runs for an account the machine page no longer lists, and every module serving accounts always serves the default. |

## The default account

A machine has exactly one default account once it has any, and its row under
**Available accounts** carries the chip `ui.accounts.default` and no
**Remove** ([../ui_behavior.md](../ui_behavior.md), "The machine page").

| Rule | Reason |
| --- | --- |
| `default_account` names one available account, and empty means none. The same name is the key in the file, the attribute on `AccountListView` and `EnabledAccountsView`, and the property in `api_types.ts`. | One field names exactly one account; a flag on each row can end up true on two. A field is spelled once ([../protocol.md](../protocol.md), "The page, its members and its writes"). |
| The default is enabled in every module whose `accounts` reads `several` ("Which modules serve which accounts"), first in its list; an account checked later goes after it. | The clients take a module's first enabled account as the machine's default for terminals, SSH and mounts ([../protocol.md](../protocol.md), "The sections"; [../client.md](../client.md), "SSH for other programs"), so they need no change. |
| Setting a default installs nothing the person did not install. Terminal and the SSH server, which the agent carries, enable it at once, and a module of the account layer whose `want` is neither empty nor `absent` gets it in the same write. Any other module gets it in the write of its **Install** or **Start**, under the same hold of `CONFIG_WRITE_LOCK` as its `want`, with its secrets generated there. | The default is written into each module's file and never derived at composition: `config/` is the only source of truth, and composition stays a read that generates no secret. |
| The default's row in a module is checked and cannot be cleared: `<name>/set` with a list that leaves it out is refused `account_is_default {account}`. | A module serving accounts always serves the account a client reaches with no account named. |
| The SSH server runs one instance for the default on every machine that has one. On Windows a standard default account is granted the batch logon right with its task, and the right is taken back with its last task ([module_template.md](module_template.md), "The run"). | A client reaches a shell through the SSH server, and the default is the account it reaches. |
| The default's Home share is always on: File share enables the default as every module serving several accounts does. Its **Install** first reads the default's share path, or its home for an empty one, with the agent's `folder` verb. | A share whose folder is missing or is a link is refused before anything is written ([modules/file_share.md](modules/file_share.md), "A share's folder"). |
| On Windows and macOS Containers runs in the default account's Podman machine ([modules/containers.md](modules/containers.md), "The account and its machine"), and Hermes WebUI, Ayakaleaf and AstrBot use the gateway while the default account's AI switch is on ("The AI switch and what follows it"). | Each serves one account, and the default is the one account every machine with any has. |
| The default is never changed. `POST /api/agent/module/account/default/set` is taken only while the machine has no default or its default is gone ("When the default is gone"), and refused 409 `default_account_exists {account}` otherwise. | A change is not lossless: Containers' data on Windows and macOS stays in the old account's Podman machine, and the gateway apps follow another switch. A wrong pick is undone by a new join ("A wrong default"). |
| The hub's own machine gets its default at setup. Both wizards show one more screen after the proxy screen and before **Ready**, **Your account on this machine**: a picker over the machine's accounts and, on Windows, a password field, with the line that the account cannot be changed later. The review names it **Default account** ([../ui_behavior.md](../ui_behavior.md), "The setup page"). | A hub on one machine then needs no further step on its machine page. Linux and macOS step down from root and need no password, and Windows starts a process as another account only with its password. |
| The hub reads the machine's accounts for that screen with the agent's rule, copied into `neutrino_hub/platforms/` and pinned by the agent's test cases. A machine where the rule finds none gets no screen, the review reads `—`, and the machine is incomplete until an account is added on its page. | The hub's own agent is installed after the questions are answered, and a root-only server has no account to pick. |
| The picker starts at the account that ran setup: in the terminal `SUDO_USER` on Linux and macOS and the elevated process's own account on Windows; in the browser, or where neither names one, the account at the screen; else the first in the list. | Enter takes the default on every screen of the terminal wizard. |
| The answers document, the one `nhub setup --stdin` reads, gains `default_account: {account, password}`, `password` on Windows alone, required while the rule finds an account. `wizard.from_document` rejects an account the rule does not find and an empty Windows password. `SetupContext` gains `accounts` and the suggested `default_account`. | The terminal, the browser and `--stdin` build one document ([../architecture.md](../architecture.md), "`nhub setup` configures and starts, and installs nothing"). |
| The setup step that writes the answers stores a Windows password as a vault login named `<host name> / <account>`, and writes `setup_default_account.json`, `{account, login_id}`, mode 0600, under the state root ([../files.md](../files.md)). | The vault is made in that step, and the hub's own agent joins later, in another process. |
| At the first report of the hub's own machine that lists accounts, while that file exists and the machine has no default, and when the report lists the account: on Windows the hub tests the login with the agent's `account_password_test`, on a thread of its own. On a pass, and always on Linux and macOS, it writes the account as available and default, enables it in Terminal and the SSH server, and pushes the state. A failed test, or an account the report does not list, deletes the login. The file is deleted either way. | Only the agent's report names the accounts and tests a Windows password, and the hub already writes at a machine's first report ([../protocol.md](../protocol.md), "The modules section, one entry per module"). A failure leaves the hub's own machine incomplete, fixed in one step on its page. |
| A machine joined by a link, `nagent join`, `install.sh agent`, `install.ps1` or **Add over SSH** carries no account, and is incomplete until an account is added on its machine page. An account added to a machine with no default, or whose default is gone, becomes its default, after a confirmation that it cannot be changed. | Each further machine takes one step on its machine page. |
| While a machine has no default or its default is gone, every other available account's row has **Make default**, which writes `account/default/set` after the same confirmation. | An upgraded machine with several accounts, and one whose default is gone, have accounts and no default to serve. |

## Which modules serve which accounts

Every row of the hub's description table names the accounts its module
serves in the field `accounts` ([module_template.md](module_template.md),
"The hub side"): `several`, one instance or record per enabled account;
`one`, a tie to the machine's default account; `none`, nothing that runs as
a person's account. The table below is the one list of every module with
its kind chip, how it runs and its install method
([../agent.md](../agent.md), "The kinds of module";
[module_install.md](module_install.md), "The source chip and the kind
chip"), in the description table's order.

| Module | Kind chip | How it runs | Install method (source chip) | `accounts` |
| --- | --- | --- | --- | --- |
| Terminal | Account service | carried by the agent | `agent` (Built-in) | `several`: shells and `exec` commands as each enabled account |
| SSH server | Account service | carried by the agent | `agent` (Built-in) | `several`: one instance per enabled account |
| Remote desktop | System service | carried by the agent | `agent` (Built-in) | `none`: the seat, whoever is at the screen |
| File share | System service | software the module configures | `system` on Linux, `builtin` on Windows and macOS (System) | `several`: one Home share and one SMB user per enabled account |
| Gitea | System service | a service with a system account of its own | `hub` (Upstream) | `none`: its own account, LocalSystem on Windows |
| Ollama | System service | a service with a system account of its own | `hub` (Upstream) | `none`: its own account, SYSTEM on Windows |
| VS Code | Account service | a program run as a person's account | `hub` (Upstream) | `several`: one instance per enabled account |
| code-server | Account service | a program run as a person's account | `hub` (Upstream) | `several`: one instance per enabled account |
| CloudCLI | Account service | a program run as a person's account | `hub` (Upstream) | `several`: one instance per enabled account, with its own npm install |
| Codeg | Account service | a program run as a person's account | `hub` (Upstream) | `several`: one instance per enabled account |
| Claude Code | Program | a command line program per account | `hub` (Upstream) | `several`: each enabled account's `PATH` reaches the module's copy first |
| Codex | Program | a command line program per account | `hub` (Upstream) | `several`: each enabled account's `PATH` reaches the module's copy first |
| OpenCode | Program | a command line program per account | `hub` (Upstream) | `several`: each enabled account's `PATH` reaches the module's copy first |
| SiYuan | Account service | a program run as a person's account | `hub` (Upstream) | `several`: one instance per enabled account, with a gateway key while that account's AI switch is on |
| Containers | System service | software the module configures | `system` on Linux (System), `hub` on Windows and macOS (Upstream) | `one`: on Windows and macOS the default account's Podman machine; on Linux root, tied to no account |
| Hermes WebUI | System service | container images | `container` (Container) | `one`: its gateway follows the default account's AI switch |
| Ayakaleaf | System service | container images | `container` (Container) | `one`: its gateway follows the default account's AI switch |
| AstrBot | System service | container images | `container` (Container) | `one`: its gateway follows the default account's AI switch |

| Rule | Reason |
| --- | --- |
| A module whose `accounts` reads `several` is a module of the account layer: its tab holds **Enabled accounts**, the default is enabled in it as "The default account" says, its row checked and locked, and the person checks other available accounts beside it. | One field gives the locked row, the install's write and the guide's words on adding more accounts, so the three cannot drift. |
| A module whose `accounts` reads `one` holds no list of accounts and serves the default alone: the hub composes its tie from `default_account`. | It is one copy for the whole system, and the default is the one account every machine with any has. |
| A module whose `accounts` reads `none` runs as no person's account: as its own system account, as root or SYSTEM, or at the seat. | Nothing it runs changes with the accounts. |

## The AI switch and what follows it

Each available account's switch, **AI tools use the hub's gateway**, decides
whether what runs as that account uses the gateway
([ai_tools.md](ai_tools.md)). A system service that uses the gateway runs
as no person's account, and the default account's switch decides for it.

| Rule | Reason |
| --- | --- |
| An account service, or a program run as an account, follows the AI switch of the account it runs as: the account's AI tools, Codeg's sessions through them, and the account's SiYuan instance. A system service that uses the gateway, Hermes WebUI, Ayakaleaf or AstrBot, follows the default account's switch. | Each account's switch is the one control over that account's files, and a system service has no account of its own. |
| The state gives Hermes WebUI, Ayakaleaf and AstrBot `is_gateway_used` in their configuration: the default account's `is_ai_tools_enabled`, and true while the machine has no default. A default that is gone keeps deciding by its stored switch. | The agent reads "off" from a field of its own, since an empty `model` already means the gateway serves nothing yet and leaves everything as it is. A machine with no default keeps the wiring it had. The field is added and keeps `PROTOCOL`, so an older agent ignores it and stays wired ([../protocol.md](../protocol.md), "Versioning"). |
| While `is_gateway_used` is false, the hub composes no `NEUTRINO_GATEWAY_URL`, no `NEUTRINO_GATEWAY_KEY` and no `AI_` variable into the module's containers, and voids the module's gateway key. It generates a new key when the field turns true again. | No key works outside the switch, as the device's own key follows its accounts' switches ([../hub_components/ai.md](../hub_components/ai.md), "A key per device as well as per client"). |
| With the field true and no model served, the agent rewrites nothing: an empty served list is not off. | A gateway restart must not rewrite the apps' settings. |
| SiYuan's gateway key for an account exists while the account is enabled and its switch is on, and is voided when either turns off. `settle_instance_keys` runs at every change of a switch as at every change of the enabled accounts. | The account's own switch decides that account's SiYuan, as it decides its AI tools. |
| The agent's AI gateway forward is open on a managed machine while some account's switch is on, or while some container module is installed with `is_gateway_used` true; the hub's check of an `ai` stream reads the same. On the hub's own machine `gateway_port` is the gateway's `listen_port` while some container module is installed with `is_gateway_used` true, and 0 otherwise ([../agent.md](../agent.md), "The AI gateway forward"). | SiYuan's key exists only while its account's switch is on, which already opens the forward. The relay serves only an app that uses the gateway. |

What each app holds while it uses the gateway, and what is taken out while
it does not, is the app's own page:

| App | While its switch is on | While it is off | What of the person's stays |
| --- | --- | --- | --- |
| Ayakaleaf | the four `AI_` variables and the two `NEUTRINO_GATEWAY_` ones, a change restarting the app ([modules/ayakaleaf.md](modules/ayakaleaf.md), "The model") | none of them, and the app restarts | the tab's **AI model**, kept in `ayakaleaf.json` for the next time the switch is on |
| Hermes WebUI | the two variables, and the agent's six keys in `config.yaml` ([modules/hermes_webui.md](modules/hermes_webui.md), "The gateway") | no variable; each key that still holds what the agent wrote is unset, and `model_overrides.custom` goes | a default the person saved in the page, a chat's own model, every other key |
| AstrBot | the gateway's source, the agent's provider and the default it set ([modules/astrbot.md](modules/astrbot.md), "The gateway") | the default reset where it names the agent's provider, the agent's provider deleted, and the source deleted while no provider of the person's is on it | the person's providers, a default naming one of them, the other profiles |
| SiYuan, for each account | the module's provider in the account's `conf.json` ([modules/siyuan.md](modules/siyuan.md), "The gateway") | the provider taken out, and `ai.agent.modelId` and `ai.editing.modelId` emptied where they named one of its models | the person's providers, and a model id naming one of them |

## When the default is gone

| Rule | Reason |
| --- | --- |
| The default is gone when the machine's last report lists accounts and does not list it. The machine then reads incomplete and is greyed as a machine with no default is ("A machine with no default"). | A Windows read that fails lists no account at all, and must not turn a machine incomplete. |
| Each module keeps the gone default enabled, and that account's instance alone fails ("An account the system no longer has"). | A missing account in one report can come back, and the person decides when it goes. |
| The person makes another available account the default with **Make default**, or adds one, which becomes it. The new default comes first in Terminal, the SSH server and every installed module serving several accounts, added where it is missing, as "The default account" says; the gone default stays enabled after it. Once another account is the default, the gone one's row has **Remove**, which takes it out of every module. | It is the path of any machine with no default, and the row is the person's to remove. |
| On Windows and macOS Containers moves to the new default's Podman machine, which the agent makes as at a first install, and the gone account's keeper is removed as SYSTEM or root. Hermes WebUI, Ayakaleaf and AstrBot follow the new default's switch. | Nothing can run as an account the system no longer has. |

## A wrong default

| Rule | Reason |
| --- | --- |
| A joined machine's default changes only through a new join: **Forget** on the Agents page, the agent uninstalled from the machine, then installed and joined again. The new row has no default, and its first account added becomes the default. | **Forget** deletes `config/devices/<id>/`, the default with it. A rejoin after `nagent leave` keeps the row and its default, and a blank link is matched to the row by the machine's id ([../agent.md](../agent.md), "Joining: one ticket, thirty minutes, spent in one step"). The uninstall takes away what the old default's modules made. |
| The hub's own machine changes its default only through a new hub: the hub uninstalled with its configuration, installed again and set up, its account screen shown again. | The default comes from its setup, and an uninstall that keeps `config/` keeps the default ([../files.md](../files.md), "What each operation leaves behind"). |

## A machine with no default

| Rule | Reason |
| --- | --- |
| Until a machine has a default, the hub composes its state from what is stored: each module's enabled accounts, SiYuan's keys, Containers' Podman machine in the account the stored Run settings name, and Hermes WebUI, Ayakaleaf and AstrBot with `is_gateway_used` true. The hub pushes no change because a default is missing. | Modules already running keep running, and the machine changes nothing until the person sets its accounts up. |
| The panel greys every module's actions, every apply bar and **+ Add module**, with `ui.modules.default_needed` as the reason; **Available accounts** stays live ([../ui_behavior.md](../ui_behavior.md), "The machine page"). The hub rejects those writes with 409 `default_account_missing`: every POST under `/api/agent/module/` but those under `account/`, and `device/remote_desktop/password/set` and `device/desktop/seat_password/reset`. | The person sets the accounts and the default first, on the machine page, and a write from another caller meets the same 409. |
| The agent has nothing of its own for it: a joined machine with no available account runs the three modules the agent carries with no instance, and the SSH server reads `stopped`. | The agent carries out the state the hub sends it ([../agent.md](../agent.md), "Who may tell the agent what"). |
| A machine online with no default, or whose default is gone, is incomplete: the sidebar's machine group shows a `warn` dot and `state.incomplete` at the right of its row, where an offline machine shows `state.offline`, and offline wins. The Agents table and the machine page's header show the same dot and word. `GET /api/hub/device` gives each row `default_account` and `is_default_account_missing` ([../ui_behavior.md](../ui_behavior.md), "The Agents page"). | One state has one word everywhere, and amber means a state that waits for the person ([../visual.md](../visual.md), "Colour carries one meaning each"). |
| Once at the panel's start, beside `move_legacy_device_files`, each `accounts.json` with no `default_account` key, as 0.6.1 wrote it, gets the key: its one available account when it has exactly one, with no other condition, and empty for several or none. The one account moves first in every module file that enables it, and is added to Terminal, the SSH server and every module of the account layer whose `want` is neither empty nor `absent`. | This step is the one transition code, deleted once 0.6.1 is no longer an upgrade source. A file that holds the key, empty included, is never read by it again. |
| After that step Hermes WebUI, Ayakaleaf and AstrBot follow the one account's switch: an off switch takes them off the gateway, and turning it on brings them back. A machine with several accounts or none is incomplete. | The default's switch is their one rule, and one press of the switch brings the gateway back. |
