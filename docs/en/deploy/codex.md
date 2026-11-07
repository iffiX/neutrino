# Codex

Codex is the command-line AI coding tool from OpenAI. Neutrino Hub installs it for the accounts you select, and you run `codex` in a terminal on that system to use it.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

Codex is a plain program: it runs only while you run it, and has no start or stop. Its source is **Upstream**, which means the hub downloads it from the publisher, as [App kinds](/en/deploy/app_kinds) describes. Codex is released under the Apache-2.0 license.

## Supported systems

| System                   | Architecture         | First Neutrino Hub version |
| ------------------------ | -------------------- | -------------------------- |
| Linux                    | amd64, arm64         | 0.6.0                      |
| Windows 10 1809 or later | amd64, arm64         | 0.6.0                      |
| macOS 13 or later        | Apple silicon, Intel | 0.6.0                      |

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on. Check that **Available accounts** lists your account. If it does not, add it as [Add an account](/en/deploy/on_a_machine#add-an-account) describes.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Codex** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_codex_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Codex card marked in red](/guide/en/deploy_codex_02_catalog.webp "Select Codex")
   ![The Codex card highlighted, with the Close button marked in red](/guide/en/deploy_codex_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Codex** row in the list on the left, and its tab opens on the right. Select **Install**, and the tab lists each step.

   ![The module list with the Codex row marked in red](/guide/en/deploy_codex_04_tab.webp "Select Codex")
   ![The Codex tab showing not installed, with the Install button marked in red](/guide/en/deploy_codex_05_install.webp "Select Install")
   ![The tab showing installing, with each step listed](/guide/en/deploy_codex_06_installing.webp "Installing")

1. When the installation finishes, the tab shows **ready**. As a plain program, Codex has only **Install**, **Uninstall** and **Configure** on its tab, without **Start** or **Stop**. Select **Configure**, and under **Enabled accounts**, select each account that uses Codex.

   ![The tab showing ready, with the Configure button marked in red](/guide/en/deploy_codex_07_installed.webp "Select Configure")
   ![The Enabled accounts field with the lab row marked in red](/guide/en/deploy_codex_08_tick_account.webp "Select lab")

1. If the account's shell already runs another copy of Codex, such as one you installed yourself, selecting the account opens a dialog. The dialog shows the location and version of that copy and the version of the module's copy. It also states that the other copy stays as it is. Select **Replace** to make this account use the module's copy, or select **Cancel** or outside the dialog to leave the account unselected.

   ![The dialog for replacing the copy lab runs, with the Replace button marked in red](/guide/en/deploy_codex_09_replace_dialog.webp)

   Your own copy stays unchanged, and you can still update or uninstall it yourself.

1. Select **Apply Codex**. The agent puts the module's copy first on the PATH of each selected account. When it finishes, the account row shows the version of the module's copy.

   ![lab selected, with the Apply Codex button marked in red](/guide/en/deploy_codex_10_apply.webp "Select Apply Codex")
   ![The lab row showing the version of the module's copy](/guide/en/deploy_codex_11_applied.webp "Applied")

On Windows, if another copy of Codex is on the system PATH, the dialog title states that the account cannot use this module's copy. The only button is **Close**, and the account stays unselected. Windows searches the system PATH before the user PATH, so the module's copy cannot come first. To make this account use the module's copy, uninstall the other copy, or remove its folder from the system PATH.

## Use

Before you start, you need a terminal for this account on this system. You can open it on the system itself or from the client, as [Terminal](/en/deploy/terminal) describes.

1. Open a new terminal. A terminal opened before you selected the account keeps its old PATH and cannot find the module's copy.
1. Run `codex`. On the first run, follow the prompts on the screen to sign in with your own ChatGPT account or an OpenAI API key. OpenAI sets the fees.

   ![A terminal running codex, showing the first-run screen](/guide/zh/deploy_codex_12_terminal.webp)

SSH connections through Neutrino work the same way, such as `nclient ssh` and Remote-SSH in VS Code. A new SSH session puts the selected programs first on the PATH. Selecting or clearing an account leaves open SSH sessions connected, and those sessions keep their old PATH.

To make Codex use the hub's AI gateway, edit this account under **Available accounts** on the system page. Turn on **AI tools use the hub's gateway** and select **Save**, following [AI gateway](/en/hub/ai_gateway#systems-joined-to-the-hub). The account row on the Codex tab then shows **Uses the hub's AI gateway**, or **Uses its own settings** while the switch is off. The switch is outside the Codex tab, and a change to it takes effect without **Apply Codex**.

## Share

Codex has no web page, so [App share](/en/share/web_share) cannot generate a link for it. To use Codex in a browser, install [Codeg](/en/deploy/codeg) and share it.

## Risks and limits

Codex running in a terminal can do anything this account can do, including reading and writing every file of this account.

The hub manages the version.

After you select an account, its row shows a notice and the **Put this module's copy first** button in these cases:

- The shell of this account runs another copy of Codex first, such as one you installed later. The notice shows the location and version of that copy.
- The shell of this account cannot find the module's copy.

When you select the button, the agent moves the line in the startup file back to the end of the file. On Windows, the agent puts the module's program folder first on the user PATH again. The agent changes nothing back until you select the button. After you edit the startup file, the notice in the row updates automatically.

![The lab row with a red notice, and the Put this module's copy first button marked in red](/guide/en/deploy_codex_13_conflict.webp)

## Settings

Apart from selecting accounts, the following settings can stay at their defaults:

| Setting                            | Where                                         | What it does                                                                                                           |
| ---------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Enabled accounts**               | **Configure** on the Codex tab                | The selected accounts use the Codex the module installed                                                               |
| **AI tools use the hub's gateway** | The account form under **Available accounts** | Makes this account's Codex use the [AI gateway](/en/hub/ai_gateway); the account row on the Codex tab shows the result |

After you select an account, the agent makes its shell find the module's copy first, with these changes on each system:

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

When you clear this account, the agent removes the program folder of Codex from `env.sh`, and on Windows, from the user PATH. [Claude Code](/en/deploy/claude_code) uses the same `env.sh` and the same line. When neither module has this account selected, the agent deletes the line and `env.sh`. The startup files of the account then return to their original state.

## Uninstall

On the **Codex** tab, select **Uninstall**, then confirm in the dialog. The dialog states that each account's settings in `~/.codex` stay, and so does any Codex installed outside this module.

![The uninstall dialog of Codex, with the Uninstall button marked in red](/guide/en/deploy_codex_14_uninstall_dialog.webp)

The agent deletes only the folders whose names clearly belong to Neutrino Hub. Shared folders such as `~/.local/share`, `~/.local` and `~/.config/fish` stay.
