# 访问没有安装被控端的设备

你可以在外部网络访问打印机、路由器这类不能安装软件的设备。

如果你只要打开它们的网页，先试试[加入已有的服务](/deploy/services)，这种方式不用配置路由。下面的方式让你的设备直接连接中枢所在的网段，只有 [NetBird](/access/netbird) 和 [EasyTier](/access/easytier) 支持，其他外部访问不支持。

路由由你在 NetBird 或 EasyTier 的控制台里手动设置，中枢不管理这些路由。使用应用、终端、文件和远程桌面时不用配置路由，因为这些连接都经过中枢。

## 开始之前

你要确认满足下面的条件。

- 中枢已经加入这个虚拟网，你的设备也已经连接这个虚拟网。
- 你在这个账号的控制台里有管理员权限。
- 你知道要访问的网段，比如 `192.168.1.0/24`。

如果要查询网段，到面板 **外部访问** 页的 **NetBird** 卡片查看 **局域网路由**。这里列出中枢所在电脑的每个网段，按网段可以复制。

![NetBird 卡片的局域网路由一栏](/guide/zh/access_netbird_05_routes.webp)

## NetBird

下面的步骤都在 NetBird 的控制台里操作。

1. 打开 NetBird 的控制台，进入 **Networks**，按 **Add Network**，填写名称。

   ![NetBird 控制台的一个网络，里面有一个资源 home LAN](/guide/zh/deploy_without_agent_01_netbird_network.webp)

1. 接着按 **Add Resource**，在 **Address** 里粘贴刚才复制的网段。

   <div class="pic-holder">图：Add Resource 的弹窗</div>

1. 再按 **Add Policy**。来源选择客户端所在的分组，目标选择这个资源，协议选择 **All**。客户端的分组显示在控制台 **Setup Keys** 列表的 **Groups** 一栏。

   <div class="pic-holder">图：Add Policy 的弹窗</div>

1. 最后按 **Add Routing Peer**，选择中枢，再按 **Submit**。

   <div class="pic-holder">图：Add Routing Peer 的弹窗</div>

## EasyTier

如果你使用控制台，步骤如下。

1. 打开 EasyTier 的控制台，在 **网络** 下选择中枢所在的网络，打开 **子网路由**。

   ![EasyTier 控制台的子网路由，列出一条经过中枢的路由](/guide/zh/deploy_without_agent_05_easytier_subnet.webp)

1. 按 **新增路由**，填写 **目标网段**，经过的设备选择中枢，再按 **创建路由**。

   <div class="pic-holder">图：新增路由的弹窗</div>

1. 回到面板的 **EasyTier** 卡片，**控制台下发的网络** 的 **子网路由** 一栏会列出这个网段。

   <div class="pic-holder">图：EasyTier 卡片的子网路由一栏</div>

如果你选择了 **手动引导节点**，就没有控制台。这时在卡片的 **导出的局域网** 里勾选网段，再按 **应用 EasyTier 设置**。

## 验证连接

1. 让你的设备离开中枢所在的局域网，比如让手机使用移动网络。
1. 确认客户端的 **虚拟网** 一行显示 **已连接**。
1. 在浏览器里打开那个设备的局域网地址。如果能打开，就说明配置成功。

在 Android 上第一次连接虚拟网时，系统会弹出授权框，选择允许。iPhone 的 App 里没有虚拟网这一行，你要用 NetBird 或 EasyTier 自己的 App 加入。

## 连接失败的处理

如果你使用 NetBird，检查控制台里有没有给这个分组放行的策略。

如果你使用 EasyTier，并且客户端一直显示 **连接中…**，说明它还没有挂载到网络。你要到控制台把它挂载到网络。

如果面板 **外部访问** 页顶部有红字，说明路由和中枢的网段重叠，见[故障排查](/reference/troubleshooting)。

中枢会删除默认路由 `0.0.0.0/0`，所以你只添加具体的网段。

## 风险

这种连接方式不经过中枢的权限检查。这个虚拟网的成员能访问这个网段上每台设备的每个端口，只依靠设备自身的登录防护。
