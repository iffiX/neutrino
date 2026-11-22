# Ollama

Ollama 是在你自己的电脑上运行大语言模型的服务程序。你在面板里为一个系统安装 Ollama 并拉取模型，再从客户端或 AI 网关使用这些模型。

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.1" />

每个系统只运行一个 Ollama，所有账户共用它和它的模型，所以你不用选择账户。它的来源是外部源，由中枢从发布方下载，见[应用的分类](/deploy/app_kinds)。Ollama 以 MIT 许可证发布。

## 支持的系统

| 系统                  | 架构              | 开始支持的微子·中枢版本 | 安装包                                   |
| --------------------- | ----------------- | ----------------------- | ---------------------------------------- |
| Linux                 | amd64、arm64      | 0.6.1                   | 约 1.6 GB，安装时一起安装系统软件包 zstd |
| Windows               | amd64             | 0.6.1                   | 约 1.6 GB                                |
| macOS 14 或更新的版本 | Apple 芯片、Intel | 0.6.1                   | 约 190 MB                                |

中枢从 GitHub 或 SourceForge 下载安装包，哪个测速更快就用哪个。中国大陆没有 Ollama 安装包的镜像，下载速度取决于中枢访问这两个网站的速度。

## 安装

1. 在浏览器里打开面板并登录，再到左侧栏的下半部分，点你要安装到的系统。
1. 在 **模块配置** 区域，按 **+ 添加模块**。在弹窗里勾选 **Ollama** 卡片，卡片亮起后按 **关闭**。

   ![模块列表，添加模块按钮标红](/guide/zh/deploy_ollama_01_add_module.webp "按 + 添加模块")
   ![添加模块的弹窗，Ollama 的卡片标红](/guide/zh/deploy_ollama_02_catalog.webp "勾选 Ollama")
   ![Ollama 的卡片亮了，关闭按钮标红](/guide/zh/deploy_ollama_03_catalog_ticked.webp "按 关闭")

1. 弹窗关闭后，在左边的列表里点 **Ollama** 这一行，右边会显示它的标签。按 **安装**。

   ![模块列表，Ollama 这一行标红](/guide/zh/deploy_ollama_04_tab.webp "点 Ollama")
   ![Ollama 标签显示未安装，安装按钮标红](/guide/zh/deploy_ollama_05_install.webp "按 安装")

1. 标签会列出每一步：中枢先下载安装包，再发给被控端。标签变成 **已安装** 后，按 **启动**。标签变成 **运行中** 时，安装完成。

   ![标签显示安装中，下面列出每一步](/guide/zh/deploy_ollama_06_installing.webp "安装中")
   ![标签显示已安装，启动按钮标红](/guide/zh/deploy_ollama_07_installed.webp "按 启动")

如果这个系统上已经有你自己安装的 Ollama，面板直接使用它：

| 系统           | 你自己安装的 Ollama                                   | 面板上的显示                                                                                                                                    |
| -------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux          | 服务 `ollama.service`，来自 Ollama 的安装脚本或软件包 | 标签显示 **已安装**。你第一次按 **启动** 时，被控端开始管理这个服务。按 **卸载** 时，这个服务恢复成第一次按 **启动** 之前的状态，你的文件都保留 |
| Windows、macOS | Ollama 应用，在你登录系统时启动                       | 应用运行时，标签上只有 **配置**，并显示 **这里用的是这个系统上已安装的 Ollama 应用。** 应用没有运行时，按 **安装** 会失败                       |

你自己安装的 Ollama 由你自己升级，面板只管理它的模型。如果安装失败，查看[故障排查](/reference/troubleshooting)。

## 使用

### 拉取模型

Ollama 能拉取它自己模型库里的模型，比如 `qwen2.5:7b`，也能拉取 Hugging Face、ModelScope 上的 GGUF 仓库。在中国大陆，用 ModelScope 的名称拉取。模型由这个系统上的 Ollama 下载，所以这个系统要能访问模型的来源。

1. 在 **Ollama** 标签上按 **配置**，下面会显示 **模型** 区域。还没有模型时，列表显示 **还没有模型。**

   ![标签显示运行中，配置按钮标红](/guide/zh/deploy_ollama_17_started.webp "按 配置")
   ![模型区域，输入框标红](/guide/zh/deploy_ollama_08_models_empty.webp "模型区域")

1. 在输入框里填写模型名称，再按 **拉取**。下面是 ModelScope 上的一个小模型，Hugging Face 的名称以 `hf.co/` 开头：

   ```text
   modelscope.cn/unsloth/SmolLM2-135M-Instruct-GGUF:Q4_K_M
   ```

   ![输入框里填好了 ModelScope 的模型名称，拉取按钮标红](/guide/zh/deploy_ollama_09_pull.webp)

1. 列表里出现这个模型，显示进度条、已下载的大小、总大小和速度。拉取由中枢负责，你关闭页面后拉取继续进行。之后再拉取的模型显示 **排队中**，按顺序拉取。

   ![拉取中的模型，显示进度条和速度](/guide/zh/deploy_ollama_10_pulling.webp)

1. 拉取完成后，这一行显示 **参数量**、**量化**、**大小** 和 **修改时间**，右上角显示模型个数和总大小。

   ![拉取完成的模型，右上角显示 1 个模型](/guide/zh/deploy_ollama_11_pulled.webp)

按 **取消** 停止拉取，已下载的部分保留，以后拉取同一个名称时接着下载。拉取失败时，这一行显示失败原因，直到你按 **取消**。

程序使用一个模型时，Ollama 把它加载到内存，这一行显示 **已加载，占用** 和内存大小。按 **移出内存** 释放内存，模型文件保留。按 **删除** 并在弹窗里确认，模型就从这个系统上删除。

![已加载的模型，移出内存按钮标红](/guide/zh/deploy_ollama_12_loaded.webp "按 移出内存")
![删除模型的弹窗，删除按钮标红](/guide/zh/deploy_ollama_13_remove_dialog.webp "按 删除")

### 从客户端连接

开始之前，你要把电脑加入中枢，见[加入中枢](/access/join)。这台电脑还要有 **端口** 权限，你在面板的 **客户端** 页设置，见[客户端](/hub/clients)。

1. 打开客户端，进入 **应用** 页，找到 **Ollama** 这一行。这一行下面显示本机地址 `127.0.0.1` 和一个端口号。按 **使用**。

   ![客户端的应用页，Ollama 这一行的使用按钮标红](/guide/zh/deploy_ollama_40_client_use.webp)

1. **使用** 变成 **停止**，这时这台电脑上的程序能连接 Ollama 的 API。Ollama 没有网页，所以这一行没有 **打开**。

   ![Ollama 这一行显示停止按钮](/guide/zh/deploy_ollama_41_client_in_use.webp)

下面的命令列出这个系统上的模型，`<local-port>` 是 **Ollama** 这一行显示的端口号：

```bash
curl http://127.0.0.1:<local-port>/api/tags
```

其他使用 Ollama API 的工具，地址也填写 `http://127.0.0.1:<local-port>`。按客户端里这一行的 **配置**，可以修改本机端口。使用中这个按钮是灰色的，要先按 **停止**。

### 通过 AI 网关使用

这个系统在线、Ollama 运行并且至少有一个模型时，中枢把这些模型加入 [AI 网关](/hub/ai_gateway)，名称和 Ollama 里的相同。使用网关的工具都能选择这些模型。这时面板 **AI** 页的 **提供方** 列表里，会多出一行 **来自 my-computer 的 Ollama**，其中 my-computer 是这个系统的名称。按这一行的 **模型**，面板打开这个系统的 Ollama 标签和它的 **模型** 区域。

![AI 页的提供方列表，来自 my-computer 的 Ollama 这一行标红](/guide/zh/hub_ai_gateway_30_ollama_row.webp)

## 分享

Ollama 没有网页，不能用[应用分享](/share/web_share)生成链接。如果别人要用这些模型，把对方的电脑加入中枢，再在 **客户端** 页打开它的 **端口** 权限。

## 注意

Ollama 的 API 没有登录。能连接它的程序都能使用、拉取和删除模型，包括：

- 这个系统上所有账户的程序，它们连接 `127.0.0.1:11434`。
- 按了 **使用** 的电脑上的所有程序，它们连接这台电脑的本机端口。

Ollama 只监听 `127.0.0.1`，局域网里的其他电脑要通过客户端连接。

Ollama 的云端模型已关闭，这个系统只运行已拉取的模型。一个模型通常有几 GB，拉取前确认磁盘空间。

## 设置

除了拉取模型，下面的设置保持默认即可。

| 设置                          | 位置                               | 作用                     |
| ----------------------------- | ---------------------------------- | ------------------------ |
| **模型**                      | Ollama 标签的 **配置**             | 拉取、移出内存和删除模型 |
| **更新**、**安装另一个版本…** | 标签的状态下面                     | 更换 Ollama 的版本       |
| **配置**                      | 客户端 **应用** 页的 Ollama 这一行 | 修改这台电脑上的本机端口 |

被控端启动 Ollama 时，监听地址固定为 `127.0.0.1:11434`，模型保存在下面的目录里：

| 系统    | 模型目录                                                                | 运行 Ollama 的账户 |
| ------- | ----------------------------------------------------------------------- | ------------------ |
| Linux   | `/var/lib/neutrino/agent/ollama_data/models/`                           | `neutrino_ollama`  |
| macOS   | `/Library/Application Support/Neutrino/agent/state/ollama_data/models/` | `neutrino_ollama`  |
| Windows | `%ProgramData%\Neutrino\agent\state\ollama_data\models\`                | SYSTEM             |

## 卸载

在 **Ollama** 标签上按 **卸载**。弹窗说明，拉取的模型都留在它的数据目录里。确认后按 **卸载**。

![Ollama 标签，卸载按钮标红](/guide/zh/deploy_ollama_50_uninstall.webp "按 卸载")
![卸载的弹窗，卸载按钮标红](/guide/zh/deploy_ollama_51_uninstall_dialog.webp "确认")

再次安装后，原来的模型仍然可以使用。在 Linux 和 macOS 上，账户 `neutrino_ollama` 也保留。
