---
title: "One-click deploy ComfyUI"
description: "Neutrino Hub deploys ComfyUI in one click on Linux, Windows or an Apple silicon Mac to make images and video, and Claude Code can drive it."
---

# ComfyUI

ComfyUI is a program that makes images and video from node workflows. You wire a model, a prompt, a sampler and other nodes into a graph, and ComfyUI computes the result step by step. Neutrino Hub installs ComfyUI on one system, and you work in it in a browser through a client.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.3" />

Each system runs one ComfyUI, as a service account of its own. Only the system's default account reads and writes its models and outputs, and only that account's AI tools can drive it. You choose no account, and no other account can be turned on for it. An Intel Mac cannot install it, and its card in the Add module dialog is grey. Its source is **Upstream** and its kind is **System service**, as [App kinds](/en/deploy/app_kinds) describes. ComfyUI is released under the GPL-3.0 license.

## Supported systems

| System            | Architecture  | First Neutrino Hub version |
| ----------------- | ------------- | -------------------------- |
| Linux             | amd64, arm64  | 0.6.3                      |
| Windows           | amd64         | 0.6.3                      |
| macOS 14 or later | Apple silicon | 0.6.3                      |

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **ComfyUI** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_comfyui_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the ComfyUI card marked in red](/guide/en/deploy_comfyui_02_catalog.webp "Select ComfyUI")
   ![The ComfyUI card highlighted, with the Close button marked in red](/guide/en/deploy_comfyui_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **ComfyUI** row in the list on the left, and its tab opens on the right. Select **Install**.

   ![The module list with the ComfyUI row marked in red](/guide/en/deploy_comfyui_04_tab.webp "Select ComfyUI")
   ![The ComfyUI tab showing not installed, with the Install button marked in red](/guide/en/deploy_comfyui_05_install.webp "Select Install")

1. The tab lists each step: Python, uv, ComfyUI and comfy-mcp, a check of the install, the account neutrino_comfyui, then ComfyUI's Python packages. That last step downloads PyTorch, from about 1 GB to 7.5 GB depending on the hardware ComfyUI runs on, as [Settings](#settings) lists. On Linux with CPU, the whole install takes one to two minutes. When the tab shows **installed**, select **Start**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_comfyui_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_comfyui_07_installed.webp "Select Start")

1. The tab shows **starting** first. The first start is slower than later ones, under a minute on Linux and about two minutes on Windows. The install is complete when the tab shows **running**.

   ![The tab showing running](/guide/en/deploy_comfyui_17_running.webp)

At install the hub sets **Runs on** from the system's graphics cards. An NVIDIA card gives NVIDIA, an AMD card on Linux gives AMD, an Intel Arc card gives Intel Arc, and any other system gets CPU. A Mac has no such setting; ComfyUI there uses the PyTorch built for Apple silicon. If the install fails, see [Troubleshooting](/en/reference/troubleshooting).

## Use

### Open it from a client

Before you start, join your phone or computer to the hub, as [Join the hub](/en/access/join) describes.

In the client, open the **Apps** page and find the **ComfyUI** row. Select **Use**, and the row shows a local address with the buttons **Stop**, **Configure** and **Open**. Select **Open**.

![The client's Apps page with the Use button of the ComfyUI row marked in red](/guide/en/deploy_comfyui_40_client_use.webp "Select Use")
![The row with a local address, and the Open button marked in red](/guide/en/deploy_comfyui_41_client_open.webp "Select Open")

The browser opens ComfyUI's page with no password to type.

![ComfyUI in the browser](/guide/en/deploy_comfyui_16_visitor.webp)

A new ComfyUI has no models. The model nodes of a workflow read from the **Models folder**, whose path the panel's **Settings** shows. Put the model files you downloaded into its subfolders, for example a full model into `checkpoints`.

Copy the files in instead of moving them. A file moved from your home folder keeps its old permissions, and ComfyUI cannot read it. If you moved one, select **Stop** and then **Start** on the panel's **ComfyUI** tab. The agent then sets the permissions of those files again.

The default account reads and writes the **Models folder** and the `input` and `output` folders beside it in the same data folder. ComfyUI saves the images and videos it makes in `output`.

### Install custom nodes

A custom node is a node someone else wrote, and ComfyUI runs its code. Install one with ComfyUI-Manager in ComfyUI's page. The default account cannot put files into the `custom_nodes` folder itself.

After each start of ComfyUI, ComfyUI-Manager reads the list of every node from the internet, which takes a few minutes. An install before the read ends reports is not a CNR node; wait a few minutes and install it again.

### Let AI tools drive ComfyUI

The default account can also have [Claude Code](/en/deploy/claude_code), [Codex](/en/deploy/codex) or [OpenCode](/en/deploy/opencode). Neutrino Hub then adds an MCP server named `comfyui`, which is comfy-mcp, to each of them. Open the tool in that account's terminal and ask it to work with ComfyUI: read the hardware it runs on, search and download models, run a workflow, fetch the images it made.

![Claude Code reading ComfyUI's system information through comfyui](/guide/en/deploy_comfyui_60_claude_mcp.webp)

A model a tool downloads goes straight into the **Models folder**, and ComfyUI uses it with no restart. The model each AI tool talks to follows the default account's **AI tools use the hub's gateway** switch, as [AI gateway](/en/hub/ai_gateway#systems-joined-to-the-hub) describes. comfy-mcp cannot install custom nodes, and it cannot start or stop ComfyUI; do the first in ComfyUI's page and the second in the panel. The tools of other accounts have no such MCP server.

## Share

ComfyUI can generate a link with [App share](/en/share/web_share), and the visitor opens it in a browser.

1. In the panel's left sidebar, select **Services**. Find the **ComfyUI** row and select **Share**.

   ![The Services page with the Share button of the ComfyUI row marked in red](/guide/en/deploy_comfyui_12_services_share.webp)

1. In the dialog, enter a **Name** that helps you recognize the link; the name is visible only to you. The yellow notice under it states that the visitor uses this app as neutrino_comfyui, the account that runs ComfyUI. **Expires** defaults to 7 days, and you can choose another option. Select **Generate link**.

   ![The share dialog with the Name field marked in red](/guide/en/deploy_comfyui_13_share_dialog.webp "Enter a name")
   ![The share dialog filled in, with the Generate link button marked in red](/guide/en/deploy_comfyui_14_share_generate.webp "Select Generate link")

1. Select **Copy** right away and send the link to the visitor. Then select **Done** to close the dialog. After the dialog closes, the panel no longer shows the link.

   ![The share dialog showing the link and a QR code, with the link row marked in red](/guide/en/deploy_comfyui_15_share_link.webp "Select Copy")

The visitor signs in to nothing and works in your workspace. They see your inputs, outputs, queue and history, run workflows, and install custom nodes with ComfyUI-Manager.

## Risks and limits

ComfyUI has no sign-in. Programs of every account on the system can connect to it, run workflows, upload files, and install custom nodes through ComfyUI-Manager.

A custom node's code runs as the account that runs ComfyUI. The Python packages it installs have no pinned version and can replace ComfyUI's own packages, PyTorch among them. Install only nodes you trust.

Models and the files ComfyUI makes stay in its data folder. A model is often several GB, so check the free disk space before you add one.

## Settings

These settings can stay at their defaults. On the **ComfyUI** tab, select **Configure**, and the **Settings** section opens.

| Setting              | What it does                                                                                                                                                |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Runs on**          | The hardware ComfyUI uses: **NVIDIA GPU (CUDA)**, **AMD GPU (ROCm)**, **Intel Arc GPU (XPU)** or **CPU**. Not shown on a Mac                                |
| **Idle unload time** | How long after the last job ends before the model leaves memory: **5 minutes**, **30 minutes**, **1 hour**, **4 hours** or **Never**; 30 minutes by default |
| **Models folder**    | The folder that holds the models, shown for reading only                                                                                                    |

Select **Apply settings** after a change. A new idle unload time takes effect right away, and ComfyUI keeps running. A new **Runs on** makes the hub download its PyTorch; ComfyUI stops during the download and starts again after it.

![The Settings section with the Runs on field marked in red](/guide/en/deploy_comfyui_30_settings.webp "Settings section")
![A new Runs on picked, with the Apply settings button marked in red and the download notice above it](/guide/en/deploy_comfyui_31_settings_apply.webp "Select Apply settings")

Each choice of hardware has its own PyTorch, and the system decides which choices it offers:

| **Runs on**             | Systems                | Download size                        |
| ----------------------- | ---------------------- | ------------------------------------ |
| **NVIDIA GPU (CUDA)**   | Linux, Windows         | about 4 GB on Linux, 3 GB on Windows |
| **AMD GPU (ROCm)**      | Linux amd64            | 7.5 GB                               |
| **Intel Arc GPU (XPU)** | Linux amd64, Windows   | 3.4 GB on Linux, 2.3 GB on Windows   |
| **CPU**                 | Linux, Windows         | about 1 GB                           |
| not shown               | macOS on Apple silicon | 0.9 GB                               |

The **Models folder** is `data/models` inside ComfyUI's data folder. Each system keeps the data folder here and runs ComfyUI as this account:

| System  | Data folder                                                       | Account that runs ComfyUI |
| ------- | ----------------------------------------------------------------- | ------------------------- |
| Linux   | `/var/lib/neutrino/agent/comfyui_data/`                           | `neutrino_comfyui`        |
| macOS   | `/Library/Application Support/Neutrino/agent/state/comfyui_data/` | `neutrino_comfyui`        |
| Windows | `%ProgramData%\Neutrino\agent\state\comfyui_data\`                | LOCAL SERVICE             |

## Uninstall

On the **ComfyUI** tab, select **Uninstall**. The dialog states that the models, inputs, outputs and custom nodes stay in its data folder. Select **Uninstall** to confirm.

![The ComfyUI tab with the Uninstall button marked in red](/guide/en/deploy_comfyui_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button marked in red](/guide/en/deploy_comfyui_51_uninstall_dialog.webp "Confirm")

The uninstall removes ComfyUI's Python environment and caches, and the `comfyui` server in the AI tools. A new install sets up ComfyUI and its Python environment again, PyTorch download included, and the old models and custom nodes are ready to use. On Linux and macOS, the `neutrino_comfyui` account stays as well.
