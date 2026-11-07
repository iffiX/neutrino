# iOS 应用

iOS 应用是微子·中枢的 iPhone 客户端。你用自己的 Apple ID 签名并安装一次后，就能在 iPhone 上使用电脑上的应用和文件。

<Facts editions="国际版,国内版" since="0.6.0" />

App 不在 App Store，也不在 TestFlight。你要下载 `.ipa` 文件，用自己的 Apple ID 签名后安装。系统要求是 iOS 16 或更新的版本。

## 安装

1. 打开发布页，可以选择[国际版](https://github.com/iffiX/neutrino/releases/latest)或[国内版](https://cnb.cool/iffi-X/neutrino/-/releases)。下载 `neutrino-client-<版本>-ios.ipa`，国内版的文件名带 `-cn`。

1. 用 USB 线把 iPhone 连到电脑，在电脑上打开签名工具，登录你的 Apple ID，把这个文件签名并安装到手机上。签名工具可以用 Sideloadly 或 AltStore（Windows、macOS），也可以用 Impactor（Linux、macOS、Windows）。下图是 Impactor，右上角显示它已经找到用 USB 连着的 iPhone，按 **Import .ipa / .tipa** 选择刚下载的文件。

   ![Impactor 的窗口，右上角显示 USB 连着的 iPhone](/guide/zh/access_ios_02_impactor.webp)

1. 在 iPhone 上打开 **设置** → **隐私与安全性** → **开发者模式**，打开开关。iPhone 会要求重启，重启后再确认一次。

   ![开发者模式的开关已打开，开关标红](/guide/zh/access_ios_03_developer_mode.webp)

1. 第一次打开 App 时，屏幕会显示 **不受信任的开发者**，这是因为签名用的是你自己的 Apple ID。按 **取消**。

   ![不受信任的开发者的提示，开发者名字已打码](/guide/zh/access_ios_05_untrusted_phone.webp)

1. 打开 **设置** → **通用** → **VPN与设备管理**，在 **开发者 App** 下面点你的 Apple ID。按 **信任**，再在弹窗里按 **信任**。下面显示 **微子** 和 **已验证** 时，这一步就完成了。

   ![设置里的设备管理，开发者 App 下面的一行标红](/guide/zh/access_ios_06_device_management.webp "点你的 Apple ID")
   ![信任的弹窗，信任按钮标红](/guide/zh/access_ios_07_trust_dialog.webp "按 信任")
   ![微子这一行显示已验证](/guide/zh/access_ios_08_trusted.webp "已验证")

1. 再打开 App。如果屏幕显示 **允许“微子”使用无线数据？**，选择 **无线局域网与蜂窝网络**。只选无线局域网时，手机离开无线网络就连不上中枢。

   ![允许微子使用无线数据的提示，无线局域网与蜂窝网络标红](/guide/zh/access_ios_09_wireless_data_phone.webp)

1. 按 **加入中枢**，再扫描面板上的二维码，或者把链接粘贴到下面的输入框里，按 **加入**。面板上的步骤见[加入中枢](/access/join)。

   ![加入中枢页，粘贴链接的输入框标红](/guide/zh/access_ios_10_join.webp)

免费 Apple ID 的签名 7 天后到期，手机上同时最多有 3 个这样的 App，你要在到期前重新签名。付费 Apple ID 的签名有效期是一年。升级时，把新的 `.ipa` 签名后安装在旧版本上。

## 连接中枢

App 会同时尝试连接中枢的每个地址，并使用最先连接成功的地址。使用直连、SakuraFrp、OpenFrp、SSH 中继时，你不用安装其他软件。

使用虚拟网时步骤不同，App 里没有虚拟网这一行。你要在手机上安装 NetBird 或 EasyTier 自己的 App，并加入同一个虚拟网。如果国区没有这些 App，你可以使用美区账号。NetBird 或 EasyTier 连接或断开时，App 会重新尝试连接。

## 应用

按钮和 [Android 应用](/access/android)相同：先按 **使用**，再按 **打开**。

![iPhone 的应用页，Gitea 这一行的打开按钮标红](/guide/zh/access_ios_20_apps.webp)

**打开** 会在 App 自带的浏览器里打开网页，按左上角的返回箭头可以关闭这个页面。入口一直打开，直到你按 **停止**。

自带浏览器的页面共用一份登录记录，所以两个应用可能互相退出登录，这时再按一次 **打开**。端口入口只在 App 显示在屏幕上时才能使用。

## 文件

共享不会出现在系统的“文件”应用里，你要在 App 里查看。

1. 在这一行按 **打开**，进入 App 里的共享页。这里一屏显示一个文件夹。

1. 点文件可以预览，再用预览里的分享按钮把它保存到别处。

1. 右下角的 **+** 里有 **从“文件”上传**、**从“照片”上传** 和 **新建文件夹**。

   ![共享页右下角的菜单展开，有新建文件夹和两种上传](/guide/zh/access_ios_21_share_menu.webp)

每行的菜单里有 **重命名**、**存储到“文件”** 和 **删除**。一次传输一个文件，其余文件显示 **等待中**，都可以 **取消**。手动声明的共享第一次要填写用户名和密码，再按 **连接**。

## 终端和桌面

**终端** 和 **桌面** 的用法与 [Android 应用](/access/android)相同。

![iPhone 上打开的终端，显示 lab 的提示符](/guide/zh/access_ios_22_terminal.webp)

## 切换到其他应用后

在 iPhone 上，切换到其他应用后，连接只保留约 30 秒，然后全部关闭。你回到 App 时，它会自动重新连接，入口恢复到原来的端口。

普通终端会结束，打开了 **持久** 或 **共享** 的终端在你回到 App 后可以继续连接。正在传输的文件会显示中断，这时按 **重试**。如果你在这段时间内回到 App，桌面仍然连接。超过这段时间后，你要重新按 **连接**。

## 设置

修改 **语言** 和 **主题** 后按 **保存**。**关于** 里的本机显示 iPhone 这样的型号，不是你给手机起的名称。
