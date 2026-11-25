---
title: "One-click deploy OpenCode"
description: "Neutrino Hub installs OpenCode in one click on Windows, macOS or Linux, connects it to the AI gateway with one switch, and lets you code from your phone."
---

# OpenCode

OpenCode is an open source AI coding tool for the command line, published by Anomaly. Neutrino Hub installs it for the enabled accounts, and you run `opencode` in a terminal on that system to use it.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.1" />

OpenCode is a plain program: it runs only while you run it, and has no start or stop. Its source is **Upstream**, which means the hub downloads it from the publisher, as [App kinds](/en/deploy/app_kinds) describes. OpenCode is released under the MIT license.

## Supported systems

| System                   | Architecture         | First Neutrino Hub version |
| ------------------------ | -------------------- | -------------------------- |
| Linux                    | amd64, arm64         | 0.6.1                      |
| Windows 10 1809 or later | amd64, arm64         | 0.6.1                      |
| macOS 13 or later        | Apple silicon, Intel | 0.6.1                      |

## Multiple accounts

OpenCode is installed for the system's default account, so the install needs no account choice. For another account, select **Configure**, check the account under **Enabled accounts**, and select **Apply OpenCode**; see [Add more accounts](/en/deploy/on_a_machine#add-more-accounts).

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **OpenCode** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_opencode_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the OpenCode card marked in red](/guide/en/deploy_opencode_02_catalog.webp "Select OpenCode")
   ![The OpenCode card highlighted, with the Close button marked in red](/guide/en/deploy_opencode_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **OpenCode** row in the list on the left, and its tab opens on the right. Select **Install**, and the tab lists each step.

   ![The module list with the OpenCode row marked in red](/guide/en/deploy_opencode_04_tab.webp "Select OpenCode")
   ![The OpenCode tab showing not installed, with the Install button marked in red](/guide/en/deploy_opencode_05_install.webp "Select Install")
   ![The tab showing installing, with each step listed](/guide/en/deploy_opencode_06_installing.webp "Installing")

1. When the installation finishes, the tab shows **ready**, and the install is complete. The agent has already put the module's copy first on the default account's PATH. As a plain program, OpenCode has only **Install**, **Uninstall** and **Configure** on its tab, without **Start** or **Stop**.

   ![The tab showing ready, with the Configure button marked in red](/guide/en/deploy_opencode_07_installed.webp)

## Use

Before you start, you need a terminal for this account on this system. You can open it on the system itself or from the client, as [Terminal](/en/deploy/terminal) describes.

1. Open a new terminal. A terminal opened before the install keeps its old PATH and cannot find the module's copy.
1. Run `opencode`. OpenCode opens its interface in the terminal, with an input box in the middle and the current model under it. On the first run, the model is Big Pickle from OpenCode. To use a provider of your own, type `/connect` in the input box and follow the prompts. The provider you choose sets the fees.

   ![A terminal running opencode, showing the first-run screen](/guide/zh/deploy_opencode_12_terminal.webp)

SSH connections through Neutrino work the same way, such as `nclient ssh` and Remote-SSH in VS Code. A new SSH session puts the selected programs first on the PATH. Selecting or clearing an account leaves open SSH sessions connected, and those sessions keep their old PATH.

To make OpenCode use the hub's AI gateway, edit this account under **Available accounts** on the system page. Turn on **AI tools use the hub's gateway** and select **Save**, following [AI gateway](/en/hub/ai_gateway#systems-joined-to-the-hub). The account row on the OpenCode tab then shows **Uses the hub's AI gateway**, or **Uses its own settings** while the switch is off. The switch is outside the OpenCode tab, and a change to it takes effect without **Apply OpenCode**.

With the switch on, the account's `~/.config/opencode/opencode.json` gains the provider `neutrino`, which OpenCode lists as **Neutrino Hub**. The providers and settings already in the file stay. If the file names no `model`, the agent sets it to `neutrino/<model>`, so OpenCode starts on the hub's model. Here `<model>` is the model this account uses through the AI gateway. A `model` the file already names stays as it is, and OpenCode starts on that model. In that case, type `/models` in the input box and choose a model under **Neutrino Hub**. When you turn the switch off, the file goes back to what it was before you turned it on.

## Share

This module installs only the command-line program, and the panel has no OpenCode web page, so [App share](/en/share/web_share) cannot generate a link for it.

## Risks and limits

OpenCode running in a terminal can do anything this account can do, including reading and writing every file of this account.

The hub manages the version, as [Change the version](/en/deploy/on_a_machine#change-the-version) describes. At each start, OpenCode checks npm and shows a notice when a newer version exists. The hub's version list does not always hold that version. To turn the check off, add `"autoupdate": false` to `~/.config/opencode/opencode.json` of this account. `opencode upgrade` and `/update` install OpenCode only through the account's own package managers, such as npm or Homebrew. The module's copy belongs to root, and these commands leave it unchanged.

On Windows, Windows searches the system PATH before the user PATH. So if another copy of OpenCode is on the system PATH, this account runs that copy. To make this account use the module's copy, uninstall the other copy, or remove its folder from the system PATH.

OpenCode accepts comments in `opencode.json`, but the agent edits that file with cc-switch, which cannot read a file that holds comments. With comments in the file, turning on **AI tools use the hub's gateway** fails, and the account row shows the cause. Remove the comments, then turn the switch off and on again.

## Settings

The following settings can stay at their defaults:

| Setting                            | Where                                         | What it does                                                                                                                 |
| ---------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**               | **Configure** on the OpenCode tab             | The selected accounts use the OpenCode the module installed                                                                  |
| **AI tools use the hub's gateway** | The account form under **Available accounts** | Makes this account's OpenCode use the [AI gateway](/en/hub/ai_gateway); the account row on the OpenCode tab shows the result |

After an account is enabled, the agent makes its shell find the module's copy first, with these changes on each system:

| System  | What the agent sets up                                                                                                                                                             |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux   | Writes `~/.local/share/neutrino/agent/env.sh` and adds a line that loads it at the end of this account's startup file. The file puts the module's program folder first on the PATH |
| macOS   | The same as Linux, with the file at `~/Library/Application Support/Neutrino/agent/env.sh`                                                                                          |
| Windows | Puts the module's program folder first on the user PATH of this account                                                                                                            |

The startup file that gets the line depends on the login shell of this account:

| Login shell  | Startup file                                                                                               |
| ------------ | ---------------------------------------------------------------------------------------------------------- |
| bash         | `~/.bashrc`, plus a login file: `~/.bash_profile`; without it, `~/.bash_login`; without that, `~/.profile` |
| zsh          | `~/.zshrc`                                                                                                 |
| fish         | `~/.config/fish/config.fish`, where the line loads `env.fish` next to `env.sh`                             |
| Other shells | `~/.profile`                                                                                               |

When you clear this account, the agent removes the program folder of OpenCode from `env.sh`, and on Windows, from the user PATH. The Codex and Claude Code modules use the same `env.sh` and the same line. When none of the three modules has this account selected, the agent deletes the line and `env.sh`. The startup files of the account then return to their original state.

## Uninstall

On the **OpenCode** tab, select **Uninstall**, then confirm in the dialog. The dialog states that each account's settings in `~/.config/opencode` stay, and so does any OpenCode installed outside this module.

![The uninstall dialog of OpenCode, with the Uninstall button marked in red](/guide/en/deploy_opencode_14_uninstall_dialog.webp)

While it runs, OpenCode also writes `~/.local/share/opencode`, `~/.local/state/opencode` and `~/.cache/opencode` in the account's home folder. The first one holds its sessions and logs. All three stay after the uninstall. The agent deletes only the folders whose names clearly belong to Neutrino Hub. Shared folders such as `~/.local/share`, `~/.local` and `~/.config/fish` stay.
