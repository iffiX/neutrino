---
title: "One-click deploy Claude Code"
description: "Neutrino Hub installs Claude Code in one click on Windows, macOS or Linux, connects it to the hub's AI gateway, and lets you keep coding from your phone."
---

# Claude Code

Claude Code is the command-line AI coding tool from Anthropic. Neutrino Hub installs it for the enabled accounts, and you run `claude` in a terminal on that system to use it.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Claude Code is a plain program: it runs only while you run it, and has no start or stop. Its source is **Upstream**, which means the hub downloads it from the publisher, as [App kinds](/en/deploy/app_kinds) describes. Claude Code is closed source, and you use it under the legal agreements of Anthropic.

## Supported systems

| System                   | Architecture         | First Neutrino Hub version |
| ------------------------ | -------------------- | -------------------------- |
| Linux                    | amd64, arm64         | 0.6.0                      |
| Windows 10 1809 or later | amd64, arm64         | 0.6.0                      |
| macOS 13 or later        | Apple silicon, Intel | 0.6.0                      |

## Multiple accounts

Claude Code is installed for the system's default account, so the install needs no account choice. For another account, select **Configure**, check the account under **Enabled accounts**, and select **Apply Claude Code**; see [Add more accounts](/en/deploy/on_a_machine#add-more-accounts).

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Claude Code** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_claude_code_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Claude Code card marked in red](/guide/en/deploy_claude_code_02_catalog.webp "Select Claude Code")
   ![The Claude Code card highlighted, with the Close button marked in red](/guide/en/deploy_claude_code_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Claude Code** row in the list on the left, and its tab opens on the right. Select **Install**, and the tab lists each step.

   ![The module list with the Claude Code row marked in red](/guide/en/deploy_claude_code_04_tab.webp "Select Claude Code")
   ![The Claude Code tab showing not installed, with the Install button marked in red](/guide/en/deploy_claude_code_05_install.webp "Select Install")
   ![The tab showing installing, with each step listed](/guide/en/deploy_claude_code_06_installing.webp "Installing")

1. When the installation finishes, the tab shows **ready**, and the install is complete. The agent has already put the module's copy first on the default account's PATH. As a plain program, Claude Code has only **Install**, **Uninstall** and **Configure** on its tab, without **Start** or **Stop**.

   ![The tab showing ready, with the Configure button marked in red](/guide/en/deploy_claude_code_07_installed.webp)

## Use

Before you start, you need a terminal for this account on this system. You can open it on the system itself or from the client, as [Terminal](/en/deploy/terminal) describes.

1. Open a new terminal. A terminal opened before the install keeps its old PATH and cannot find the module's copy.
1. Run `claude`. On the first run, follow the prompts on the screen to sign in with your own Claude account. Anthropic sets the fees.

   ![A terminal running claude, showing the first-run screen](/guide/zh/deploy_claude_code_12_terminal.webp)

SSH connections through Neutrino work the same way, such as `nclient ssh` and Remote-SSH in VS Code. A new SSH session puts the selected programs first on the PATH. Selecting or clearing an account leaves open SSH sessions connected, and those sessions keep their old PATH.

To make Claude Code use the hub's AI gateway, edit this account under **Available accounts** on the system page. Turn on **AI tools use the hub's gateway** and select **Save**, following [AI gateway](/en/hub/ai_gateway#systems-joined-to-the-hub). The account row on the Claude Code tab then shows **Uses the hub's AI gateway**, or **Uses its own settings** while the switch is off. The switch is outside the Claude Code tab, and a change to it takes effect without **Apply Claude Code**.

## Share

Claude Code has no web page, so [App share](/en/share/web_share) cannot generate a link for it. To use Claude Code in a browser, install [CloudCLI](/en/deploy/cloudcli) or [Codeg](/en/deploy/codeg) and share that app.

## Risks and limits

Claude Code running in a terminal can do anything this account can do, including reading and writing every file of this account.

The module's copy has the automatic update of Claude Code turned off, and the hub manages the version.

On Windows, Windows searches the system PATH before the user PATH. So if another copy of Claude Code is on the system PATH, this account runs that copy. To make this account use the module's copy, uninstall the other copy, or remove its folder from the system PATH.

## Settings

The following settings can stay at their defaults:

| Setting                            | Where                                         | What it does                                                                                                                       |
| ---------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**               | **Configure** on the Claude Code tab          | The selected accounts use the Claude Code the module installed                                                                     |
| **AI tools use the hub's gateway** | The account form under **Available accounts** | Makes this account's Claude Code use the [AI gateway](/en/hub/ai_gateway); the account row on the Claude Code tab shows the result |

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

When you clear this account, the agent removes the program folder of Claude Code from `env.sh`, and on Windows, from the user PATH. [Codex](/en/deploy/codex) and [OpenCode](/en/deploy/opencode) use the same `env.sh` and the same line. When none of these modules has this account selected, the agent deletes the line and `env.sh`. The startup files of the account then return to their original state.

## Uninstall

On the **Claude Code** tab, select **Uninstall**, then confirm in the dialog. The dialog states that each account's settings in `~/.claude` stay, and so does any Claude Code installed outside this module.

![The uninstall dialog of Claude Code, with the Uninstall button marked in red](/guide/en/deploy_claude_code_14_uninstall_dialog.webp)

The agent deletes only the folders whose names clearly belong to Neutrino Hub. Shared folders such as `~/.local/share`, `~/.local` and `~/.config/fish` stay.
