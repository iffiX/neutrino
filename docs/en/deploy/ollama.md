# Ollama

Ollama is a server that runs large language models on your own computer. You install it on a system from the panel, pull models there, and use them from a client or the AI gateway.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.1" />

Each system runs one Ollama, and every account shares it and its models, so you skip choosing an account. Its source is **Upstream**, which means the hub downloads it from the publisher, as [App kinds](/en/deploy/app_kinds) describes. Ollama is released under the MIT license.

## Supported systems

| System            | Architecture         | First Neutrino Hub version | Download                                               |
| ----------------- | -------------------- | -------------------------- | ------------------------------------------------------ |
| Linux             | amd64, arm64         | 0.6.1                      | About 1.6 GB; the install adds the zstd system package |
| Windows           | amd64                | 0.6.1                      | About 1.6 GB                                           |
| macOS 14 or later | Apple silicon, Intel | 0.6.1                      | About 190 MB                                           |

The hub downloads the archive from GitHub or SourceForge, whichever its speed test finds faster. No mirror in mainland China serves Ollama's archives, so the download speed depends on how fast the hub reaches these two sites.

## Install

1. Open the panel in a browser and sign in. In the lower part of the left sidebar, select the system to install on.
1. In **Module configuration**, select **+ Add module**. In the dialog, select the **Ollama** card. When the card is highlighted, select **Close**.

   ![The module list with the Add module button marked in red](/guide/en/deploy_ollama_01_add_module.webp "Select + Add module")
   ![The Add module dialog with the Ollama card marked in red](/guide/en/deploy_ollama_02_catalog.webp "Select Ollama")
   ![The Ollama card highlighted, with the Close button marked in red](/guide/en/deploy_ollama_03_catalog_ticked.webp "Select Close")

1. After the dialog closes, select the **Ollama** row in the list on the left, and its tab opens on the right. Select **Install**.

   ![The module list with the Ollama row marked in red](/guide/en/deploy_ollama_04_tab.webp "Select Ollama")
   ![The Ollama tab showing not installed, with the Install button marked in red](/guide/en/deploy_ollama_05_install.webp "Select Install")

1. The tab lists each step while the hub downloads the archive and sends it to the agent. When the tab shows **installed**, select **Start**. The install is complete when the tab shows **running**.

   ![The tab showing installing, with each step listed](/guide/en/deploy_ollama_06_installing.webp "Installing")
   ![The tab showing installed, with the Start button marked in red](/guide/en/deploy_ollama_07_installed.webp "Select Start")

If you installed Ollama on this system yourself, the panel uses your copy:

| System         | Your own Ollama                                                      | What the panel does                                                                                                                                                                           |
| -------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux          | The `ollama.service` unit, from Ollama's install script or a package | The tab shows **installed**. Your first **Start** puts the unit under the agent's control. **Uninstall** returns the unit to the state your first **Start** found it in, and keeps your files |
| Windows, macOS | The Ollama app, which starts when you sign in                        | While the app runs, the tab has only **Configure** and shows **The Ollama app installed on this machine serves here.** While the app is closed, **Install** fails                             |

You update your own Ollama yourself, and the panel manages only its models. If the install fails, see [Troubleshooting](/en/reference/troubleshooting).

## Use

### Pull a model

Ollama pulls models from its own library, such as `qwen2.5:7b`, and from GGUF repositories on Hugging Face and ModelScope. In mainland China, pull with a ModelScope name. The Ollama on this system downloads the model, so the system needs access to the model's source.

1. On the **Ollama** tab, select **Configure**, and the **Models** area opens under it. With no models yet, the list shows **No models yet.**

   ![The tab showing running, with the Configure button marked in red](/guide/en/deploy_ollama_17_started.webp "Select Configure")
   ![The Models area with the name field marked in red](/guide/en/deploy_ollama_08_models_empty.webp "The Models area")

1. Enter a model name in the field and select **Pull**. The following name is a small model on ModelScope, and a Hugging Face name starts with `hf.co/`:

   ```text
   modelscope.cn/unsloth/SmolLM2-135M-Instruct-GGUF:Q4_K_M
   ```

   ![A ModelScope model name in the field, with the Pull button marked in red](/guide/en/deploy_ollama_09_pull.webp)

1. The model appears in the list with a progress bar, the bytes so far, the total and the speed. The hub runs the pull, so closing the page leaves it running. Further pulls show **queued** and run in order.

   ![A model being pulled, with its progress bar and speed](/guide/en/deploy_ollama_10_pulling.webp)

1. When the pull finishes, the row shows **Parameters**, **Quantization**, **Size** and **Modified**, and the top-right corner shows the number of models and their total size.

   ![The pulled model, with 1 model shown in the top-right corner](/guide/en/deploy_ollama_11_pulled.webp)

**Cancel** stops a pull and keeps the parts already downloaded, so a later pull of the same name continues from them. A failed pull stays in the list with its reason until you select **Cancel**.

While a program uses a model, Ollama loads it into memory, and the row shows **loaded** with the memory it takes. Select **Unload** to free the memory and keep the model's files. Select **Remove** and confirm in the dialog to delete the model from this system.

![A loaded model, with the Unload button marked in red](/guide/en/deploy_ollama_12_loaded.webp "Select Unload")
![The dialog for removing a model, with the Remove button marked in red](/guide/en/deploy_ollama_13_remove_dialog.webp "Select Remove")

### Connect from a client

Before you start, add your computer to the hub, as [Join the hub](/en/access/join) describes. The computer also needs the **Ports** permission, which you set on the panel's **Clients** page. [Clients](/en/hub/clients) shows how.

1. Open the client, go to the **Apps** page, and find the **Ollama** row. The row shows a local address under it: `127.0.0.1` and a port. Select **Use**.

   ![The client's Apps page with the Use button of the Ollama row marked in red](/guide/en/deploy_ollama_40_client_use.webp)

1. **Use** turns into **Stop**, and programs on this computer can now reach Ollama's API. Ollama has no web page, so the row has no **Open**.

   ![The Ollama row showing the Stop button](/guide/en/deploy_ollama_41_client_in_use.webp)

To list the models, run the following command, with `<local-port>` replaced by the port the **Ollama** row shows:

```bash
curl http://127.0.0.1:<local-port>/api/tags
```

Any other tool that uses Ollama's API takes `http://127.0.0.1:<local-port>` as its address. **Configure** on this row in the client changes the local port. While the app is in use, the button is grey until you select **Stop**.

### Use the models through the AI gateway

While this system is online and its Ollama runs with at least one model, the hub adds the models to the [AI gateway](/en/hub/ai_gateway). They keep their names from Ollama, and every tool that uses the gateway can choose them. Under **Providers** on the panel's **AI** page, the row **from my-computer's Ollama** lists them, where my-computer is the name of this system. Its **Models** button opens the Ollama tab of this system with its **Models** area.

![The provider list on the AI page with the row from my-computer's Ollama marked in red](/guide/en/hub_ai_gateway_30_ollama_row.webp)

## Share

Ollama has no web page, so [App share](/en/share/web_share) cannot generate a link for it. For another person to use the models, add their computer to the hub and turn on its **Ports** permission on the **Clients** page.

## Risks and limits

Ollama's API has no sign-in. Any program that reaches it can use, pull and remove models, including:

- Programs of every account on this system, through `127.0.0.1:11434`.
- Every program on a computer where **Use** is on, through that computer's local port.

Ollama listens on `127.0.0.1` alone, and other computers on the LAN connect through a client.

Ollama's cloud models are off, so this system runs only the models pulled to it. Check the free disk space before a pull, since a model is often several gigabytes.

## Settings

Apart from pulling models, the following settings can stay at their defaults:

| Setting                                  | Where                                        | What it does                            |
| ---------------------------------------- | -------------------------------------------- | --------------------------------------- |
| **Models**                               | **Configure** on the Ollama tab              | Pulls, unloads and removes models       |
| **Update**, **Install another version…** | Under the tab's state                        | Changes the version of Ollama           |
| **Configure**                            | The Ollama row on the client's **Apps** page | Changes the local port on this computer |

The agent starts Ollama on `127.0.0.1:11434`, and keeps the models in these folders:

| System  | Models folder                                                           | Account that runs Ollama |
| ------- | ----------------------------------------------------------------------- | ------------------------ |
| Linux   | `/var/lib/neutrino/agent/ollama_data/models/`                           | `neutrino_ollama`        |
| macOS   | `/Library/Application Support/Neutrino/agent/state/ollama_data/models/` | `neutrino_ollama`        |
| Windows | `%ProgramData%\Neutrino\agent\state\ollama_data\models\`                | SYSTEM                   |

## Uninstall

On the **Ollama** tab, select **Uninstall**. The dialog states that the pulled models stay in its data folder. Select **Uninstall** to confirm.

![The Ollama tab with the Uninstall button marked in red](/guide/en/deploy_ollama_50_uninstall.webp "Select Uninstall")
![The uninstall dialog with the Uninstall button marked in red](/guide/en/deploy_ollama_51_uninstall_dialog.webp "Confirm")

After you install Ollama again, the same models are ready to use. On Linux and macOS, the `neutrino_ollama` account stays as well.
