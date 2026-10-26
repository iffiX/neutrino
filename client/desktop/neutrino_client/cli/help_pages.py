"""What ``-h`` prints at every level of ``nclient``, in both languages.

Each level's text has one shape: the usage line, one sentence of what it
does, one line per argument, then an example. The texts are keyed by the
words of the command, ``""`` for ``nclient`` itself and ``"ssh config"``
for ``nclient ssh config``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.cli import wording

CLIENT_HELP = {
    "en": {
        "": """Usage: nclient <command> [arguments]

The Neutrino client's command line. Every button of the window is one command here.

The program itself
  gui          run the client and its window
  quit         stop the running client

Default
  ssh          log in to a machine with ssh, and the configuration and proxy for other programs

Pages
  hub          hubs: join, leave, open the panel
  app          apps: forward and open
  ai           AI: the gateway this computer's tools point at (not on a phone)
  file         files: mount a machine's shares
  terminal     terminals: sessions on a machine
  rdp          desktops: remote desktop
  settings     settings: the client's own settings

Options
  -h, --help     print this help
  --version      the client's version
  --hub <hub>    which hub a command acts on when several are joined; not needed
                 with one, and with several a command that needs it lists their names

Add -h after any command for its arguments, such as nclient app open -h.""",
        "gui": """Usage: nclient gui

Run the client and its window. When it already runs, bring its window to the front.""",
        "quit": """Usage: nclient quit

Stop the running client: close the window, and end every forward and mount.""",
        "ssh": """Usage: nclient ssh <command> [arguments]

Log in to a machine with ssh. The agent carries its own SSH server, which takes
only the key the hub made for you and no password.

  list         the machines with ssh and the accounts each enables
  open         log in to a machine
  config       the ssh configuration for other programs
  proxy        for ProxyCommand; not typed by hand

Example: nclient ssh open lab-gpu""",
        "ssh list": """Usage: nclient ssh list

List the machines with ssh: one line per machine, then its enabled accounts,
the first being the default.

Example: nclient ssh list
  lab-gpu     iffi lab
  iffi-mac    iffi""",
        "ssh open": """Usage: nclient ssh open [<account>@]<machine> [-- <command>]

Log in to a machine. With no account the first enabled one is used; with --
the command alone runs and the command ends with it.

  machine      the machine's name, as the window names it
  account      the account to use, an enabled one
  -- command   run only this command, keeping its input, output and exit code

Example: nclient ssh open lab-gpu
         nclient ssh open lab@lab-gpu -- nvidia-smi""",
        "ssh config": """Usage: nclient ssh config <command>

The client writes one ssh configuration for every machine (~/.ssh/neutrino_config)
and writes it again whenever the machines change. These commands show it, and
decide whether ~/.ssh/config takes it in.

  show         print that configuration
  install      add one Include line to ~/.ssh/config, so ssh, scp and VS Code know <machine>.nt
  uninstall    take that Include line out

Example: nclient ssh config install""",
        "ssh config show": """Usage: nclient ssh config show

Print the path and the text of ~/.ssh/neutrino_config.""",
        "ssh config install": """Usage: nclient ssh config install

Add the line Include ~/.ssh/neutrino_config at the top of ~/.ssh/config, once.
After it ssh lab-gpu.nt, scp, sftp, rsync and VS Code Remote-SSH work directly.""",
        "ssh config uninstall": """Usage: nclient ssh config uninstall

Take the Include line out of ~/.ssh/config. Neutrino's own file stays.""",
        "ssh proxy": """Usage: nclient ssh proxy [<account>@]<machine>[.nt]

For ssh's ProxyCommand: join standard input and output to the account's SSH
server on that machine. The configuration writes ProxyCommand nclient ssh proxy %r@%h,
so it receives "account@machine.nt": the .nt is taken off; with no account
the first enabled one is used. The client must be running. Rarely typed by hand.

  machine      the machine's name, with or without .nt
  account      an enabled account""",
        "hub": """Usage: nclient hub <command> [arguments]

The hubs you joined.

  list         each hub's connection and the way it is reached
  join         join a hub with a link
  leave        leave a hub
  open         open the hub's panel in the browser, through a forward

Example: nclient hub join "neutrino://…\"""",
        "hub list": """Usage: nclient hub list

One line per hub: its name, its connection, the way it is reached (LAN, NetBird,
EasyTier, SSH relay, Direct, SakuraFrp, OpenFrp) and the round trip.""",
        "hub join": """Usage: nclient hub join <link>

Join a hub with a link the panel made. A link works once, for 30 minutes.

  link         the line the panel's New client link gives""",
        "hub leave": """Usage: nclient hub leave <hub> [--yes]

Leave a hub: end its forwards and mounts, leave its virtual network, and delete
the binding.

  hub          the hub's name, or its number in nclient hub list
  --yes        do not ask""",
        "hub open": """Usage: nclient hub open <hub>

Open this hub's panel in the browser, through the client's forward. This client
needs the panel permission.

  hub          the hub's name, or its number""",
        "app": """Usage: nclient app <command> [arguments]

The apps published on the machines. An app has one or more entries (web, port).

  list         each machine's apps, entries and local addresses
  use          use an app: forward each of its entries
  open         open the browser at its web page, once it is in use
  stop         end its forwards
  set          fix an entry's local port

Example: nclient app use gitea""",
        "app list": """Usage: nclient app list

List the apps by machine: name, source, each entry's kind and local address,
and whether it is in use.""",
        "app use": """Usage: nclient app use <app>

Use an app: forward each of its entries and print their local addresses. The
local address is <app>.<machine>.localhost:<port>, and the port does not change
after it is first given.

  app          the app's name; <machine>/<app> when two machines have one name""",
        "app open": """Usage: nclient app open <app>

Open the browser at the app's first http or https entry. The app must be in
use: nclient app use first.

  app          the app's name; <machine>/<app> when two machines have one name""",
        "app stop": """Usage: nclient app stop <app>

End this app's forwards.

  app          the app's name; <machine>/<app> when two machines have one name""",
        "app set": """Usage: nclient app set <app> --port <entry>=<port>

Fix one entry's local port. The entry names are in nclient app list.

  app                 the app's name
  --port entry=port   one at a time, and it repeats; an empty port goes back to the hub's""",
        "ai": """Usage: nclient ai <command>

Which gateway this computer's AI tools (claude, codex, gemini) point at. A phone
has no such page.

  show         where they point now
  set          write the hub's gateway into these tools' configuration""",
        "ai show": """Usage: nclient ai show

One line per tool: the gateway address it points at, and whether it is the hub's.""",
        "ai set": """Usage: nclient ai set

Write the hub's AI gateway into this computer's tools. Running it again refreshes them.""",
        "file": """Usage: nclient file <command> [arguments]

The machines' file shares. No password: the client takes it from the hub.

  list         each machine's shares and whether they are mounted here
  mount        mount a share
  unmount      unmount it

Example: nclient file mount lab-gpu""",
        "file list": """Usage: nclient file list

List the shares by machine: the share's name, where it is mounted here, and
whether it is mounted.""",
        "file mount": """Usage: nclient file mount <machine>[/<share>] [--path <path> | --drive <letter>]

Mount a share. With nothing else given it goes to the default place:
~/remote/<machine>-<share> on Linux and macOS, the first free drive letter on Windows.

  machine/share   the machine's name; the share can be left out when the machine has one
  --path          mount it at this folder (Linux, macOS)
  --drive         mount it as this drive letter (Windows), such as Z:""",
        "file unmount": """Usage: nclient file unmount <machine>[/<share>]

Unmount it.""",
        "terminal": """Usage: nclient terminal <command> <machine> [arguments]

Terminal sessions on a machine, run as an enabled account, with no password.

  list         the machine's sessions
  open         open a new shell
  attach       attach to a session
  exec         run one command
  set          change whether a session is persistent and shared
  stop         end a session

Example: nclient terminal open lab-gpu""",
        "terminal list": """Usage: nclient terminal list <machine>

The machine's sessions: the id's first characters, the account, how long it has
been open, whether it is persistent, whether it is shared, and how many are attached.""",
        "terminal open": """Usage: nclient terminal open <machine> [--account <account>]

Open a new shell in this terminal. The shell exiting ends it.

  --account    which enabled account; the first one by default""",
        "terminal attach": """Usage: nclient terminal attach <machine> <session>

Attach to a session that is still kept. Ctrl+] leaves it running.

  session      the session's id, or its first characters as nclient terminal list prints them""",
        "terminal exec": """Usage: nclient terminal exec <machine> [--account <account>] [--tty] -- <command>

Run one command; its input, its output and its exit code come back as they are.
For scripts and agents.

  --account    which enabled account; the first one by default
  --tty        give the command a terminal, for interactive programs (htop, vim,
               progress bars); without it the command runs on pipes, for scripts

Example: nclient terminal exec lab-gpu -- nvidia-smi
         nclient terminal exec lab-gpu --tty -- htop""",
        "terminal set": """Usage: nclient terminal set <machine> <session> [--persist on|off] [--share on|off]

Change a session: --persist is whether it stays after its last window detaches,
--share is whether other clients can attach.""",
        "terminal stop": """Usage: nclient terminal stop <machine> <session>

End a session, and every program in it.""",
        "rdp": """Usage: nclient rdp <command> [arguments]

Remote desktop.

  list         the machines sharing their desktop
  connect      open the viewer

Example: nclient rdp connect iffi-mac""",
        "rdp list": """Usage: nclient rdp list

One line per machine sharing its desktop: who is at the screen, and whether a
viewer is open here.""",
        "rdp connect": """Usage: nclient rdp connect <machine>

Open the viewer on this machine's desktop. The client takes the seat password
itself; nothing is typed.""",
        "settings": """Usage: nclient settings <command> [arguments]

The client's own settings, the same as the Settings page.

  show         every setting and its value
  set          change one

Example: nclient settings set language zh-CN""",
        "settings show": """Usage: nclient settings show

One line per setting: its name, its value, and the values it takes.""",
        "settings set": """Usage: nclient settings set <name> <value>

Change one setting. The names and the values they take are in nclient settings show.""",
    },
    wording.CLIENT_LANGUAGE_CHINESE: {
        "": """用法：nclient <命令> [参数]

微子客户端的命令行。窗口里每个按钮对应这里一条命令。

程序本身
  gui          运行客户端和窗口
  quit         停止运行中的客户端

默认功能
  ssh          用 ssh 登录被控端，给别的软件用的配置和代理

页面
  hub          中枢：加入、离开、打开面板
  app          应用：转发和打开
  ai           AI：本机工具指向的网关（手机端没有）
  file         文件：挂载被控端的共享
  terminal     终端：被控端上的会话
  rdp          桌面：远程桌面
  settings     设置：客户端自己的设置项

选项
  -h, --help     看这份帮助
  --version      客户端版本
  --hub <中枢>   绑定了几个中枢时，这条命令对哪一个；只绑一个时不用写，
                 绑了几个又不写就报错并列出名字

每条命令后面加 -h 看它的参数，比如 nclient app open -h。""",
        "gui": """用法：nclient gui

运行客户端和它的窗口。已经在运行就把窗口叫到前面。""",
        "quit": """用法：nclient quit

停止运行中的客户端：关窗口，收回所有转发和挂载。""",
        "ssh": """用法：nclient ssh <命令> [参数]

用 ssh 登录被控端。被控端自带 SSH 服务器，只认中枢发给你的钥匙，不用密码。

  list         开了 ssh 的机器和各自启用的账户
  open         登录一台机器
  config       给别的软件用的 ssh 配置
  proxy        给 ProxyCommand 用，不直接敲

例子：nclient ssh open lab-gpu""",
        "ssh list": """用法：nclient ssh list

列出开了 ssh 的机器：每台机器一行，后面是启用的账户，第一个是默认账户。

例子：nclient ssh list
  lab-gpu     iffi lab
  iffi-mac    iffi""",
        "ssh open": """用法：nclient ssh open [<账户>@]<机器> [-- <命令>]

登录一台机器。不写账户就用第一个启用的；写了 -- 就只跑那条命令然后退出。

  机器         机器名，和窗口里一样
  账户         要用的账户，必须是启用的
  -- 命令      只执行这条命令，保留输入输出和退出码

例子：nclient ssh open lab-gpu
      nclient ssh open lab@lab-gpu -- nvidia-smi""",
        "ssh config": """用法：nclient ssh config <命令>

客户端为每台机器写一份 ssh 配置（~/.ssh/neutrino_config），机器列表一变就重写。
这组命令看它，和决定要不要把它接进 ~/.ssh/config。

  show         打印这份配置
  install      在 ~/.ssh/config 加一行 Include，让 ssh、scp、VS Code 直接认 <机器>.nt
  uninstall    拿掉那行 Include

例子：nclient ssh config install""",
        "ssh config show": """用法：nclient ssh config show

打印 ~/.ssh/neutrino_config 的路径和内容。""",
        "ssh config install": """用法：nclient ssh config install

在 ~/.ssh/config 开头加一行 Include ~/.ssh/neutrino_config。已经有就不动。
之后 ssh lab-gpu.nt、scp、sftp、rsync、VS Code Remote-SSH 直接能用。""",
        "ssh config uninstall": """用法：nclient ssh config uninstall

拿掉 ~/.ssh/config 里那行 Include。微子自己的配置文件不删。""",
        "ssh proxy": """用法：nclient ssh proxy [<账户>@]<机器>[.nt]

给 ssh 的 ProxyCommand 用：把标准输入输出接到那台机器上该账户的 SSH 服务器。
配置文件里写的是 ProxyCommand nclient ssh proxy %r@%h，所以它收到的是
"账户@机器.nt"：.nt 后缀认得，去掉就是机器名；账户不写就用第一个启用的。
需要客户端正在运行。一般不用自己敲。

  机器         机器名，带不带 .nt 都行
  账户         启用的账户""",
        "hub": """用法：nclient hub <命令> [参数]

你绑定的中枢。

  list         每个中枢的连接状态和走的哪条路
  join         用链接加入一个中枢
  leave        离开一个中枢
  open         经转发在浏览器打开中枢面板

例子：nclient hub join "neutrino://…\"""",
        "hub list": """用法：nclient hub list

每个中枢一行：名字、连接状态、走的哪条路（局域网、NetBird、EasyTier、SSH 中转、直连、SakuraFrp、OpenFrp）、往返时间。""",
        "hub join": """用法：nclient hub join <链接>

用面板生成的链接加入一个中枢。链接只能用一次，30 分钟内有效。

  链接         面板"新建客户端链接"给出的那一串""",
        "hub leave": """用法：nclient hub leave <中枢> [--yes]

离开一个中枢：收回它的转发和挂载，退出它的虚拟网，删掉绑定。

  中枢         中枢名，或 nclient hub list 里的序号
  --yes        不再确认""",
        "hub open": """用法：nclient hub open <中枢>

经客户端的转发在浏览器里打开这个中枢的面板。需要这个客户端有面板权限。

  中枢         中枢名，或序号""",
        "app": """用法：nclient app <命令> [参数]

被控端上发布的应用。一个应用有一个或几个入口（网页、端口）。

  list         每台机器下的应用、入口、本机地址
  use          使用一个应用：给它的每个入口开转发
  open         应用在用时，在浏览器里打开它的网页
  stop         收回它的转发
  set          固定某个入口的本机端口

例子：nclient app use gitea""",
        "app list": """用法：nclient app list

按机器列出应用：名字、来源、每个入口的种类和本机地址、是否在用。""",
        "app use": """用法：nclient app use <应用>

使用一个应用：给它的每个入口开转发，并列出本机地址。
本机地址是 <应用>.<机器>.localhost:<端口>，端口第一次分配后不再变。

  应用         应用名；同名时写 <机器>/<应用>""",
        "app open": """用法：nclient app open <应用>

在浏览器里打开这个应用的第一个 http/https 入口。应用要先在用：先 nclient app use。

  应用         应用名；同名时写 <机器>/<应用>""",
        "app stop": """用法：nclient app stop <应用>

收回这个应用的转发。

  应用         应用名；同名时写 <机器>/<应用>""",
        "app set": """用法：nclient app set <应用> --port <入口>=<本机端口>

固定某个入口的本机端口。入口名在 nclient app list 里。

  应用                应用名
  --port 入口=端口    一次一个，可以重复""",
        "ai": """用法：nclient ai <命令>

这台电脑上的 AI 工具（claude、codex、gemini）指向哪个网关。手机端没有这一页。

  show         现在指向哪里
  set          把中枢的网关写进这些工具的配置""",
        "ai show": """用法：nclient ai show

每个工具一行：指向的网关地址，和它是不是中枢的。""",
        "ai set": """用法：nclient ai set

把中枢的 AI 网关写进本机工具的配置。再跑一次就是刷新。""",
        "file": """用法：nclient file <命令> [参数]

被控端的文件共享。不用密码，客户端从中枢拿。

  list         每台机器的共享和本机的挂载状态
  mount        挂载一个共享
  unmount      卸载

例子：nclient file mount lab-gpu""",
        "file list": """用法：nclient file list

按机器列出共享：共享名、挂在本机哪里、挂着没有。""",
        "file mount": """用法：nclient file mount <机器>[/<共享>] [--path <路径> | --drive <盘符>]

挂载一个共享。什么都不写就用默认位置：
Linux 和 macOS 是 ~/remote/<机器-共享>，Windows 是第一个空盘符。

  机器/共享    机器名；机器只有一个共享时共享名可以不写
  --path       挂到这个目录（Linux、macOS）
  --drive      挂到这个盘符（Windows），比如 Z:""",
        "file unmount": """用法：nclient file unmount <机器>[/<共享>]

卸载。""",
        "terminal": """用法：nclient terminal <命令> <机器> [参数]

被控端上的终端会话，以启用的账户运行，不用密码。

  list         机器上的会话
  open         开一个新 shell
  attach       接上一个会话
  exec         跑一条命令
  set          改会话的持久和共享
  stop         结束一个会话

例子：nclient terminal open lab-gpu""",
        "terminal list": """用法：nclient terminal list <机器>

机器上的会话：序号、账户、开了多久、持久不持久、共享不共享、谁在看。""",
        "terminal open": """用法：nclient terminal open <机器> [--account <账户>]

开一个新 shell，接在这个终端里。退出 shell 就结束。

  --account    用哪个启用的账户，默认第一个""",
        "terminal attach": """用法：nclient terminal attach <机器> <会话>

接上一个还在的会话。Ctrl+] 脱开，会话留着。

  会话         nclient terminal list 里的序号或 id""",
        "terminal exec": """用法：nclient terminal exec <机器> [--account <账户>] [--tty] -- <命令>

跑一条命令，输入输出和退出码原样回来。给脚本和 agent 用。

  --account    用哪个启用的账户，默认第一个
  --tty        给命令一个终端：要交互的程序（htop、vim、带进度条的）用它；
               不写就是管道，适合脚本

例子：nclient terminal exec lab-gpu -- nvidia-smi
      nclient terminal exec lab-gpu --tty -- htop""",
        "terminal set": """用法：nclient terminal set <机器> <会话> [--persist on|off] [--share on|off]

改一个会话：persist 是脱开以后还留不留，share 是别的客户端能不能接上。""",
        "terminal stop": """用法：nclient terminal stop <机器> <会话>

结束一个会话，里面的程序一起结束。""",
        "rdp": """用法：nclient rdp <命令> [参数]

远程桌面。

  list         共享着桌面的机器
  connect      打开查看器

例子：nclient rdp connect iffi-mac""",
        "rdp list": """用法：nclient rdp list

共享着桌面的机器一行一台：谁坐在屏幕前、有几个人在看。""",
        "rdp connect": """用法：nclient rdp connect <机器>

打开查看器连上这台机器的桌面。座位密码客户端自己拿，不用输。""",
        "settings": """用法：nclient settings <命令> [参数]

客户端自己的设置，和设置页一一对应。

  show         所有项和当前值
  set          改一项

例子：nclient settings set language zh-CN""",
        "settings show": """用法：nclient settings show

每项一行：项名、当前值、可选值。""",
        "settings set": """用法：nclient settings set <项> <值>

改一项。项名和可选值看 nclient settings show。""",
    },
}


def page(level: str) -> str:
    """The help one level of ``nclient`` prints, in the client's language.

    Args:
        level: The words of the command, ``""`` for ``nclient`` itself.

    Returns:
        The text; the English one where the client's language has none.

    Raises:
        KeyError: When no language has a help for that level.
    """
    table = CLIENT_HELP.get(wording.language()) or CLIENT_HELP["en"]
    return table.get(level) or CLIENT_HELP["en"][level]


def levels() -> tuple:
    """Every level that prints a help.

    Returns:
        The levels' words, ``""`` first.
    """
    return tuple(CLIENT_HELP["en"])
