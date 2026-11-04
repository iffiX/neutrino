# SSH 连接

你可以用 ssh、sftp 和 VS Code 远程开发直接连接每个系统，不用自己配置密钥。

这个功能只在电脑客户端上提供，手机上使用 **终端** 页。你要给这台电脑打开 **SSH** 权限。连接后，你能做这个账户能做的一切。

## 启用 SSH 连接

你要完成两步：在要连接的系统上打开 SSH 服务器，在你的电脑上打开客户端的开关。

1. 在面板左侧栏下半部分点要连接的系统，再选择 **SSH 服务器** 标签。在 **启用的账户** 里勾选账户，再按 **应用 SSH 服务器**。账户后面显示 **运行中** 时，这一步完成。

   ![模块列表，SSH 服务器标签标红](/guide/zh/access_ssh_05_tab.webp "选择 SSH 服务器")
   ![勾选账户，应用 SSH 服务器按钮标红](/guide/zh/access_ssh_06_tick.webp "勾选账户，按 应用")

1. 在你的电脑上打开客户端，进入 **设置** 页，打开 **让 SSH 程序直接连被控端**，再按 **保存**。

   ![设置页，让 SSH 程序直接连被控端标红](/guide/zh/access_ssh_07_setting.webp)

你也可以不打开这个开关，运行下面的命令，效果相同。之后要移除时，运行 `nclient ssh config uninstall`。

```bash
nclient ssh config install
```

```text
已在 ~/.ssh/config 里加上 Include ~/.ssh/neutrino_config
```

这个开关只在 `~/.ssh/config` 第一行添加一句 `Include`，不修改其他内容。

## 连接系统

主机名是系统在面板上的名称加上 `.nt`。如果要更换账户，写成 `ssh <账户>@<系统>.nt`。不写账户时，使用这个系统第一个启用的账户。

```bash
ssh my-computer.nt
```

如果后面跟一条命令，命令运行完后立即返回。第一次连接不用设置密码，也不用配置密钥。

```bash
ssh my-computer.nt uname -sr
```

```text
Linux 5.15.0-198-generic
```

`scp`、`sftp`、`rsync`、`git` 都可以这样使用，`rsync` 要在两端都安装。

使用 VS Code、JetBrains 的远程开发时，主机名填写 `<系统>.nt`。

<div class="pic-holder">图：VS Code 连上这个系统</div>

FileZilla 这类软件不读取 SSH 配置，这时运行 `nclient ssh list` 查询地址，再填写列出的本机地址和端口。

```text
my-computer  lab 127.0.0.1:31407
```

## 注意

客户端运行时才能连接，客户端关闭时会提示客户端没有运行。如果两台中枢有同名系统，主机名会变成 `<系统>.<中枢>.nt`。你只能转发到那个系统自己的端口。

## 密钥

密钥保存在 `~/.ssh/neutrino/`，每个系统的每个账户一个，由中枢生成，客户端自动获取。离开最后一台中枢时，客户端会删除这些密钥。

如果要更换密钥，到面板 **凭据** 页的 **SSH 密钥** 按 **轮换**，保存在其他位置的旧密钥会立即失效。
