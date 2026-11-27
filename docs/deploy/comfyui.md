---
title: "一键部署 ComfyUI"
description: "微子中枢一键部署 ComfyUI，Windows、Linux 和 Apple 芯片的 Mac 都能装，用节点工作流生成图片和视频，AI 工具也能调用。"
---

# ComfyUI

ComfyUI 是用节点工作流生成图片和视频的程序。你把模型、提示词和采样这些节点连成一张图，ComfyUI 按这张图一步一步算出结果。微子·中枢在一个系统上安装 ComfyUI，你从客户端在浏览器里使用它。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.3" />

每个系统只运行一个 ComfyUI，它以自己的服务账户运行。只有这个系统的默认账户能读写它的模型和输出，也只有默认账户的 AI 工具能调用它，所以你不用选择账户，也不能再启用其他账户。Intel 芯片的 Mac 不能安装，添加模块的弹窗里这张卡片是灰色的。它的来源是外部源，种类是系统服务，见[应用的分类](/deploy/app_kinds)。ComfyUI 以 GPL-3.0 许可证发布。

## 支持的系统

| 系统                  | 架构         | 开始支持的微子·中枢版本 |
| --------------------- | ------------ | ----------------------- |
| Linux                 | amd64、arm64 | 0.6.3                   |
| Windows               | amd64        | 0.6.3                   |
| macOS 14 或更新的版本 | Apple 芯片   | 0.6.3                   |

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **ComfyUI** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_comfyui_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，ComfyUI 的卡片标红](/guide/zh/deploy_comfyui_02_catalog.webp "勾选 ComfyUI")
   ![ComfyUI 的卡片亮了，关闭按钮标红](/guide/zh/deploy_comfyui_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **ComfyUI** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，ComfyUI 这一行标红](/guide/zh/deploy_comfyui_04_tab.webp "点 ComfyUI")
   ![ComfyUI 标签显示未安装，安装按钮标红](/guide/zh/deploy_comfyui_05_install.webp "按 安装")

1. 标签会列出每一步：安装 Python、uv、ComfyUI 和 comfy-mcp，检查安装结果，设置账户 neutrino_comfyui，最后安装 ComfyUI 的 Python 软件包。最后一步要下载 PyTorch，大约 1 GB 到 7.5 GB，取决于 ComfyUI 运行在哪种硬件上，见[设置](#设置)。在 Linux 上选 CPU 时，整个安装要一两分钟。标签变成 **已安装** 后，按 **启动**。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_comfyui_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_comfyui_07_installed.webp "按 启动")

1. 标签先显示 **启动中**。第一次启动比之后慢，Linux 上不到一分钟，Windows 上大约两分钟。标签变成 **运行中** 时，安装完成。

   ![标签显示运行中](/guide/zh/deploy_comfyui_17_running.webp)

安装时，中枢按这个系统的显卡选好 **运行在**：有 NVIDIA 显卡选 NVIDIA，Linux 上有 AMD 显卡选 AMD，有 Intel Arc 显卡选 Intel Arc，都没有就选 CPU。Mac 上没有这个选项，ComfyUI 使用为 Apple 芯片发布的 PyTorch。如果安装失败，查看[故障排查](/reference/troubleshooting)。

## 使用

### 从客户端打开

开始之前，你要先把手机或电脑加入中枢，见[加入中枢](/access/join)。

打开客户端，进入 **应用** 页，找到 **ComfyUI** 这一行。按 **使用**。这一行会多出一个本机地址，按钮变成 **停止**、**配置** 和 **打开**。按 **打开**。

![客户端的应用页，ComfyUI 这一行的使用按钮标红](/guide/zh/deploy_comfyui_40_client_use.webp "按 使用")
![这一行有了本机地址，打开按钮标红](/guide/zh/deploy_comfyui_41_client_open.webp "按 打开")

浏览器会打开 ComfyUI 的页面，你不用输入密码。

![浏览器里的 ComfyUI](/guide/zh/deploy_comfyui_16_visitor.webp)

刚安装的 ComfyUI 里没有模型。工作流里的模型节点从 **模型文件夹** 读取模型，这个文件夹的路径显示在面板的 **设置** 里。你可以把下载好的模型文件放进它的子文件夹，比如把完整的模型放进 `checkpoints`。

用复制的方式放进去，不要用移动。从你的主目录移动进来的文件保留原来的权限，ComfyUI 读不到。如果已经移动了，在面板的 **ComfyUI** 标签上按 **停止**，再按 **启动**，被控端会重新设置这些文件的权限。

默认账户能读写 **模型文件夹**，以及同一个数据目录里的 `input` 和 `output` 文件夹，ComfyUI 生成的图片和视频保存在 `output` 里。

### 安装自定义节点

自定义节点是别人写的节点，ComfyUI 运行它们的代码。你要在 ComfyUI 的页面里用 ComfyUI-Manager 安装，默认账户不能直接往 `custom_nodes` 文件夹里放文件。

ComfyUI 每次启动后，ComfyUI-Manager 要从网上读取全部节点的列表，大约要几分钟。读完之前安装节点，会提示 is not a CNR node，这时等几分钟再装。

### 让 AI 工具调用 ComfyUI

如果默认账户也安装了 [Claude Code](/deploy/claude_code)、[Codex](/deploy/codex) 或 [OpenCode](/deploy/opencode)，微子·中枢会在每个工具里添加一个名为 `comfyui` 的 MCP 服务器，也就是 comfy-mcp。在这个账户的终端里打开工具，直接让它用 ComfyUI 做事，比如查看 ComfyUI 运行在什么硬件上、搜索和下载模型、运行工作流、取回生成的图片。

![Claude Code 通过 comfyui 读出系统信息](/guide/zh/deploy_comfyui_60_claude_mcp.webp)

工具下载的模型直接放进 **模型文件夹**，ComfyUI 不用重启就能使用。AI 工具用哪个模型，跟默认账户的 **AI 工具使用中枢网关** 开关一致，见 [AI 网关](/hub/ai_gateway#加入了中枢的系统)。comfy-mcp 不能安装自定义节点，也不能启动或停止 ComfyUI，这两件事分别在 ComfyUI 的页面和面板上做。其他账户的工具没有这个 MCP 服务器。

## 分享

ComfyUI 能用[应用分享](/share/web_share)生成链接，对方用浏览器就能打开。

1. 在面板左侧栏点 **服务**，找到 **ComfyUI** 这一行，按 **分享**。

   ![服务页，ComfyUI 这一行的分享按钮标红](/guide/zh/deploy_comfyui_12_services_share.webp)

1. 弹窗打开后，在 **名称** 里填写便于你自己识别的名称，对方看不到这个名称。下面的黄色提示说明，对方会以 neutrino_comfyui 的身份使用这个应用，也就是运行 ComfyUI 的账户。**有效期** 默认是 7 天，你可以选择其他选项。选好后按 **生成链接**。立即按 **复制**，把链接发给对方，再按 **完成** 关闭弹窗。弹窗关闭后，面板不再显示这条链接。

   ![分享弹窗，名称一栏标红](/guide/zh/deploy_comfyui_13_share_dialog.webp "填写名称")
   ![分享弹窗填好了，生成链接按钮标红](/guide/zh/deploy_comfyui_14_share_generate.webp "按 生成链接")
   ![分享弹窗显示链接和二维码，链接一行标红](/guide/zh/deploy_comfyui_15_share_link.webp "按 复制")

对方打开链接后不用登录，和你使用同一个工作区：能看到你的输入、输出、队列和历史，能运行工作流，也能用 ComfyUI-Manager 安装自定义节点。

## 注意

ComfyUI 没有登录。这个系统上所有账户的程序都能连接它，运行工作流、上传文件，并通过 ComfyUI-Manager 安装自定义节点。

自定义节点的代码以运行 ComfyUI 的账户运行，它装的 Python 软件包没有固定版本，可能替换 ComfyUI 原来的软件包，包括 PyTorch。只安装你信任的节点。

模型和生成的文件都放在数据目录里，一个模型通常有几 GB，放进去之前确认磁盘空间。

## 设置

下面的设置保持默认即可。在 **ComfyUI** 标签上按 **配置**，下面显示 **设置** 区域。

| 设置                   | 作用                                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **运行在**             | ComfyUI 使用的硬件，可以选 **NVIDIA 显卡（CUDA）**、**AMD 显卡（ROCm）**、**Intel Arc 显卡（XPU）** 或 **CPU**。Mac 上不显示 |
| **空闲多久后移出内存** | 最后一个任务结束多久后，把模型移出内存，可以选 **5 分钟**、**30 分钟**、**1 小时**、**4 小时** 或 **从不**，默认是 30 分钟   |
| **模型文件夹**         | 模型所在的文件夹，只能查看                                                                                                   |

修改后按 **应用设置**。新的空闲时间立即生效，ComfyUI 不重启。换了 **运行在** 时，中枢下载对应的 PyTorch，下载期间 ComfyUI 停止，下载完后重新启动。

![设置区域，运行在一栏标红](/guide/zh/deploy_comfyui_30_settings.webp "设置区域")
![换了运行在，应用设置按钮标红，上面显示下载提示](/guide/zh/deploy_comfyui_31_settings_apply.webp "按 应用设置")

每种硬件对应一个 PyTorch，能选哪些取决于系统：

| **运行在**                | 支持的系统             | 要下载的大小                       |
| ------------------------- | ---------------------- | ---------------------------------- |
| **NVIDIA 显卡（CUDA）**   | Linux、Windows         | Linux 上约 4 GB，Windows 上 3 GB   |
| **AMD 显卡（ROCm）**      | Linux amd64            | 7.5 GB                             |
| **Intel Arc 显卡（XPU）** | Linux amd64、Windows   | Linux 上 3.4 GB，Windows 上 2.3 GB |
| **CPU**                   | Linux、Windows         | 约 1 GB                            |
| 不显示                    | macOS，使用 Apple 芯片 | 0.9 GB                             |

ComfyUI 的数据目录和运行它的账户如下，**模型文件夹** 是数据目录里的 `data/models`：

| 系统    | 数据目录                                                          | 运行 ComfyUI 的账户 |
| ------- | ----------------------------------------------------------------- | ------------------- |
| Linux   | `/var/lib/neutrino/agent/comfyui_data/`                           | `neutrino_comfyui`  |
| macOS   | `/Library/Application Support/Neutrino/agent/state/comfyui_data/` | `neutrino_comfyui`  |
| Windows | `%ProgramData%\Neutrino\agent\state\comfyui_data\`                | LOCAL SERVICE       |

## 卸载

在 **ComfyUI** 标签上按 **卸载**。弹窗说明，模型、输入、输出和自定义节点都留在它的数据目录里。确认后按 **卸载**。

![ComfyUI 标签，卸载按钮标红](/guide/zh/deploy_comfyui_50_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_comfyui_51_uninstall_dialog.webp "确认")

卸载会删除 ComfyUI 的 Python 环境和缓存，AI 工具里的 `comfyui` 也会删除。再次安装时，中枢重新安装 ComfyUI 和它的 Python 环境，PyTorch 也要重新下载，原来的模型和自定义节点仍然可以使用。在 Linux 和 macOS 上，账户 `neutrino_comfyui` 也保留。
