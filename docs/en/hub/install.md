# Install the hub

The hub is a program you install on one computer, and the panel is its web page.

Installing takes one command and the setup wizard, and then the panel runs on this computer. From then on, you install apps and add phones to the hub in the panel.

Choose a computer that stays on, because phones and other devices cannot use its apps while it is off. The computer must have internet access, and you must have administrator rights on it. Installing does not require you to register an account.

## Supported systems

| System                                                    | Architecture         | First Neutrino Hub version |
| --------------------------------------------------------- | -------------------- | -------------------------- |
| Debian 12, Ubuntu 22.04, 64-bit Raspberry Pi OS, or later | amd64, arm64         | 0.1.0                      |
| Fedora, RHEL 9, AlmaLinux 9, Rocky 9, or later            | amd64, arm64         | 0.1.0                      |
| Arch, EndeavourOS, Manjaro                                | amd64                | 0.1.0                      |
| Windows 10 1809 or later                                  | amd64                | 0.5.0                      |
| macOS 13 or later                                         | Apple silicon, Intel | 0.5.0                      |

## Run the install command

1. Open a terminal on this computer. On Linux, open the **Terminal** app. On macOS, open **Terminal** in **Applications** > **Utilities**. On Windows, search for **PowerShell** in the Start menu and open it, without selecting **Run as administrator**.

1. Copy the following command, paste it into the terminal, and press Enter. In mainland China, choose the China edition, which downloads faster. The China edition leaves out the proxy and the side gateway.

   ::: code-group

   ```bash [Linux, macOS]
   curl -fsSL https://github.com/iffiX/neutrino/releases/latest/download/install.sh | sh
   ```

   ```powershell [Windows]
   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
   ```

   ```bash [China edition, Linux and macOS]
   curl -fsSL https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.sh | sh
   ```

   ```powershell [China edition, Windows]
   irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1 | iex
   ```

   :::

1. When the script requests administrator rights, grant them one time. On Linux and macOS, type the password you sign in to this computer with, then press Enter; the screen shows no characters as you type. On Windows, select **Yes** in the permission dialog. The script then continues in a new window, and every later step happens in that window.

1. Wait for the script to finish, without taking any action. The script picks the package for this computer automatically, downloads it, verifies its checksum, then installs it. If the terminal shows `Waiting up to 300 seconds`, another program is using the system's package manager, and the script continues after that program finishes.

1. The install is complete when the terminal prints an address that starts with `http://` and contains `?token=`. The terminal prints one address for each network interface of the computer.

   ```text
   Installed neutrino-hub_0.6.0_amd64.deb
     The hub's service asks the same questions in a browser at:

       http://192.168.1.20:8080/?token=<wizard-token>

   NEUTRINO ─────────────────────────────────────
   ...
     Press Enter to begin:
   ```

The last line is `Press Enter to begin:`. Do not press Enter at this point, because the questions then move into the terminal. Keep the terminal open and continue in a browser.

## Complete the setup wizard

After **Set this box up**, the wizard has six screens. On each screen, select **Next** to go forward or **Back** to return to the previous one. The wizard writes nothing to the system until you confirm on the last screen.

The wizard and the panel open in the dark theme on your screen. The following pictures use the light theme for readability, with the same buttons and text.

1. In a browser, open the address the terminal printed. Copy the whole line, including the part after `?token=`. You can open it on this computer or on another computer on the same network. On the first screen, select **Set this box up**.

   If your browser language is Chinese, the button shows **开始配置这个系统**, and you can change the language on the next screen. If the page shows **This box is waiting to be set up**, the address is missing its token. Copy the whole line from the terminal again and open it.

   The next screen is **Language**. Open the list, select **English**, then select **Next**.

   ![The first wizard screen with the start button marked](/guide/en/hub_install_02_wizard_start.webp "Select Set this box up")
   ![The language list open with English marked](/guide/en/hub_install_03_language.webp "Select English, then Next")

1. On the **A password for the panel, a passphrase for the vault** screen, set the panel password and the vault passphrase, then select **Next**.

   - **Panel password** signs you in to the panel and has at least 8 characters. Type the same password in **Again** under it.
   - **Vault passphrase** has at least 16 characters and mixes lowercase letters, uppercase letters, digits and symbols. Type it twice as well. Write it down, because restoring a backup requires it. If you forget the passphrase, the keys in a backup cannot be recovered.
   - Leave **HTTPS for the panel** off. You can turn it on later on the [Settings: backup, updates and password](/en/hub/settings) page.

   The next screen is **What is this machine for?**. Select **Server**, then select **Next**. Server mode leaves this computer's network unchanged, and it is the choice for laptops and desktops alike. The other options in the list exist only on Linux and do not apply here. [Network modes: server, router and side gateway](/en/hub/network) describes them.

   ![Both passwords filled in with the Next button marked](/guide/en/hub_install_05_passwords.webp "Set both passwords, select Next")
   ![The machine purpose screen with Server marked](/guide/en/hub_install_06_mode_server.webp "Select Server, then Next")

1. On the **Which ports?** screen, change nothing and select **Next**. The screen lists this computer's network interfaces, and **reaches the internet** marks the one it uses for internet access. Change **Panel port** (8080) or **HTTPS port** (443) only if another program already uses that port, and keep the two ports different.

   The next screen is **Going out through a proxy**. Leave **Set it up here** off, then select **Next**. You can set up a proxy later on the [Proxy](/en/hub/proxy) page.

   ![The Which ports screen with the Next button marked](/guide/en/hub_install_07_network.webp "Change nothing, select Next")
   ![The proxy screen with the Next button marked](/guide/en/hub_install_08_exit.webp "Leave it off, select Next")

1. On the **Ready** screen, check your choices, then select **Set this box up** again. The hub starts writing to the system only at this point. The page changes to **Setting up** and lists each operation as it runs, with a green dot on each finished one. Wait for the setup to finish.

   ![The Ready screen listing every choice, with the start button marked](/guide/en/hub_install_09_ready.webp "Check, then select Set this box up")
   ![The Setting up screen showing progress step by step](/guide/en/hub_install_10_configuring.webp "Wait for the setup to finish")

   If the page shows **a step failed; the terminal has the output**, read the output in the terminal you used earlier. Then see [Troubleshooting](/en/reference/troubleshooting).

1. When **This hub is set up** appears, the hub is installed. The page opens the panel automatically after a few seconds, or you can select **Open the panel**.

   ![This hub is set up, with Open the panel marked](/guide/en/hub_install_11_done.webp)

## Sign in to the panel

1. In **Panel password**, type the password you set, then select **Sign in**.

   ![The sign-in page with the password field marked](/guide/en/hub_install_12_login.webp "Type the panel password")
   ![The password filled in with Sign in marked](/guide/en/hub_install_13_login_press.webp "Select Sign in")

1. You are signed in when the **Dashboard** page opens. This computer's name appears under **Agents** in the lower part of the sidebar, and a green dot before it means it is online. The wizard has already installed the agent on this computer and added it to the hub.

   ![The Dashboard page after sign-in](/guide/en/hub_install_14_dashboard.webp)

To open the panel later, enter the address the terminal printed in a browser, without `?token=` and the part after it, for example `http://192.168.1.20:8080`.

If you forget the address, run `sudo nhub open --print` on this computer. If the sign-in page shows **Locked after repeated failures.**, run `sudo nhub unlock`. On Windows, run both commands in an administrator PowerShell, without `sudo`.

## Install manually

If you prefer not to run the script, download the package yourself and install it:

1. Open the release page of the [International edition](https://github.com/iffiX/neutrino/releases/latest) or the [China edition](https://cnb.cool/iffi-X/neutrino/-/releases). Download the `.deb`, `.rpm`, `.pkg.tar.zst`, `.pkg` or `.msi` file for this computer, whose name starts with `neutrino-hub`.
1. Install the file, with its name in place of `<file>`. On Debian-based systems, run `sudo apt install ./<file>`; on RHEL-based systems, `sudo dnf install ./<file>`; on Arch-based systems, `sudo pacman -U <file>`. On macOS and Windows, open the file.
1. On Linux, run `sudo nhub setup`. On macOS and Windows, open **Neutrino Hub**. Then complete the setup wizard with the steps in the earlier section.

Do not use `dpkg -i` or `rpm -i`, because they skip the dependencies. On RHEL-based systems, enable the EPEL repository first. The install script enables it automatically, and a manual install requires you to enable it yourself.
