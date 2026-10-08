---
title: Your AI session on the phone
---

# Your AI session on the phone

A CloudCLI on the computer shows your account's Claude Code sessions as a web page, and the phone opens it to read and answer them.

Before you start, finish the [first step](../quick-start.md), and have Claude Code installed in your own account on the computer. Turn the phone's Wi-Fi back on.

## Start a CloudCLI

1. In the panel's sidebar, open **Modules**.
1. Under **Which machine**, select your computer.
1. Select the **CloudCLI** tab. If the tab is missing, select **+** at the end of the tabs and tick **CloudCLI**.
1. Select **Install**.
1. Select **Configure**.
1. Under **Instances**, select **Add instance**.
1. Type your account name on the computer in **Account**.
1. On Windows, pick your Windows login under **Windows login for** your account. The login comes from **Logins** on the **Credentials** page.
1. Select **Apply CloudCLI**.

The computer downloads Node.js and CloudCLI's npm packages for your account, which takes a few minutes. The tab reads **installing** until then, and the instance's row then reads **running**.

![The CloudCLI tab with one running instance](/guide/en/cloudcli_panel.webp)

When the tab reads **failed**, [Troubleshooting](../reference/troubleshooting.md) lists the code under it and the fix.

## Open it on the phone

1. In the app, open **Web**.
1. On the **CloudCLI** row with your account in parentheses, select **Open**.

![The CloudCLI row on the app's Web screen](/guide/en/app_web_cloudcli.webp)

The phone's browser opens CloudCLI already signed in, with the sessions of your account. Select a session to read it, and type into its box to answer.

![A CloudCLI session in the phone's browser](/guide/en/app_cloudcli_session.webp)

## Open it again from outside

1. Turn off Wi-Fi on the phone.
1. On **Web**, select **Open** on the same row.

The same sessions open over NetBird. The sessions use your account's own Claude Code settings, and [AI tools share the hub's gateway](./ai_gateway.md) points them at the hub instead.
