# iOS 应用

iOS 应用是微子·中枢的 iPhone 客户端。你用自己的 Apple ID 签名并安装一次后，就能在 iPhone 上使用电脑上的应用和文件。

<Facts editions="国际版,国内版" since="0.6.0" />

App 不在 App Store，也不在 TestFlight。你要下载 `.ipa` 文件，用自己的 Apple ID 签名后安装。系统要求是 iOS 16 或更新的版本。

## 安装

1. 打开发布页，可以选择[国际版](https://github.com/iffiX/neutrino/releases/latest)或[国内版](https://cnb.cool/iffi-X/neutrino/-/releases)。下载 `neutrino-client-<版本>-ios.ipa`，国内版的文件名带 `-cn`。

   <div class="pic-holder">图：发布页上的 ipa 文件</div>

1. 在电脑上用签名工具登录你的 Apple ID，把这个文件签名并安装到手机上。签名工具可以用 Sideloadly 或 AltStore（Windows、macOS），也可以用 Impactor（Linux、macOS、Windows）。

   <div class="pic-holder">图：签名工具的界面</div>

1. 在 iPhone 的设置里打开开发者模式。

   <div class="pic-holder">图：iPhone 的开发者模式开关</div>

1. 打开 App，按 **加入中枢**，再扫描面板上的二维码，或者粘贴链接。面板上的步骤见[加入中枢](/access/join)。

   <div class="pic-holder">图：iPhone 的加入中枢页</div>

免费 Apple ID 的签名 7 天后到期，手机上同时最多有 3 个这样的 App，你要在到期前重新签名。付费 Apple ID 的签名有效期是一年。升级时，把新的 `.ipa` 签名后安装在旧版本上。

## 连接中枢

App 会同时尝试连接中枢的每个地址，并使用最先连接成功的地址。使用直连、SakuraFrp、OpenFrp、SSH 中继时，你不用安装其他软件。

使用虚拟网时步骤不同，App 里没有虚拟网这一行。你要在手机上安装 NetBird 或 EasyTier 自己的 App，并加入同一个虚拟网。如果国区没有这些 App，你可以使用美区账号。NetBird 或 EasyTier 连接或断开时，App 会重新尝试连接。

## 应用

按钮和 [Android 应用](/access/android)相同：先按 **使用**，再按 **打开**。

<div class="pic-holder">图：iPhone 的应用页</div>

**打开** 会在 App 自带的浏览器里打开网页，按左上角的返回箭头可以关闭这个页面。入口一直打开，直到你按 **停止**。

自带浏览器的页面共用一份登录记录，所以两个应用可能互相退出登录，这时再按一次 **打开**。端口入口只在 App 显示在屏幕上时才能使用。

## 文件

共享不会出现在系统的“文件”应用里，你要在 App 里查看。

1. 在这一行按 **打开**，进入 App 里的共享页。这里一屏显示一个文件夹。

1. 点文件可以预览，再用预览里的分享按钮把它保存到别处。

1. 右下角的 **+** 里有 **从“文件”上传**、**从“照片”上传** 和 **新建文件夹**。

   <div class="pic-holder">图：共享页，加号菜单展开</div>

每行的菜单里有 **重命名**、**存储到“文件”** 和 **删除**。一次传输一个文件，其余文件显示 **等待中**，都可以 **取消**。手动声明的共享第一次要填写用户名和密码，再按 **连接**。

## 终端和桌面

**终端** 和 **桌面** 的用法与 [Android 应用](/access/android)相同。

<div class="pic-holder">图：iPhone 上的终端</div>

## 切换到其他应用后

在 iPhone 上，切换到其他应用后，连接只保留约 30 秒，然后全部关闭。你回到 App 时，它会自动重新连接，入口恢复到原来的端口。

普通终端会结束，打开了 **持久** 或 **共享** 的终端在你回到 App 后可以继续连接。正在传输的文件会显示中断，这时按 **重试**。如果你在这段时间内回到 App，桌面仍然连接。超过这段时间后，你要重新按 **连接**。

## 设置

修改 **语言** 和 **主题** 后按 **保存**。**关于** 里的本机显示 iPhone 这样的型号，不是你给手机起的名称。
