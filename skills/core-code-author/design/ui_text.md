# The words the panel says

Every string a person reads in the panel: switch labels and descriptions,
field hints, button text, error messages, empty states. Prose in `docs/` is
governed by [../../doc-author/](../../doc-author/SKILL.md); this page governs the
interface itself, where the reader is doing something rather than reading.

The difference is the budget. A documentation page has as many sentences as
its subject needs; a switch has one line, read at a glance, next to the thing
it changes. Almost every rule here follows from that.

## A switch's description begins "Whether"

One shape, everywhere, because a switch has one meaning and the reader should
not have to work out which half of the sentence applies to them:

```text
Whether <what is true while it is on>.
```

Not what happens when it is off; not an instruction; not a consequence. The
control already shows its state, so the description only has to name what the
state *is*.

```text
# BAD — describes the off position, so the on position is left to inference
Off leaves clients to configure themselves; the gateway still answers DNS.

# BAD — two sentences before the reader learns what the switch does
The box itself, tailscaled included, in any network mode and independently
of the LAN switch. This is the way back in when Tailscale cannot reach its
control plane over the local link.

# GOOD
Whether this network hands out addresses.

# GOOD
Whether name resolution and connections from Neutrino Hub itself go through
the proxy.
```

A consequence worth stating goes in a **second sentence**, after the first has
answered the question:

```text
Whether devices on one of the gateway's networks can reach devices on
another. Every network reaches the internet and the overlay either way.
```

Two sentences is the ceiling. A switch needing three is a switch whose page
needs a paragraph above it instead.

**Name products only where the product is the point.** A description that
names one VPN as *the* reason for a switch is wrong the day a second is
supported, and it was already wrong for anyone not running the first. Say what
the switch does to traffic; the reader knows what they run.

## Other controls

| Control | Shape | Example |
| --- | --- | --- |
| Switch | `Whether …` | `Whether this container starts with the box.` |
| Text field hint | what the field takes | `xray rule syntax: geoip:cn, geoip:private, 10.0.0.0/8.` |
| Button | the verb, imperative | `Apply nodes`, `Add node`, `Forget` |
| Empty state | what is missing, in the `No … yet` family when the list fills by itself; a second line only when the reader can do something | `No active exits yet`; `No nodes configured` / `Add one with a share link from your provider.` |
| Error | what happened, in the terms the reader used | `port 8080 is already in use on this box` |

A button says what pressing it does, never what state the system is in — and
never the same word for two different actions on one page.

## The rules that apply to everything

**No narrated reasoning.** The panel says what is, not why the code does it.
Rationale belongs in `docs/`. This is the same rule the comments obey
([../coding_style/comment.md](../coding_style/comment.md)), and it
is broken most often in descriptions that start explaining the implementation.

**Sentence case, and a full stop on a sentence.** `Send LAN traffic through
the proxy`, not `Send LAN Traffic Through The Proxy`. A label is a fragment
and takes no full stop; a description is a sentence and takes one.

**One name per thing, everywhere.** The mode is `side gateway` in every string
that names it, never `side-gateway` in one place and `Side Gateway` in
another. The config key may be `side_gateway`; what the reader sees is not the
key.

**The reader's vocabulary, not the implementation's.** `exit node`, not
`outbound`; `this network`, not `the LAN interface with the lan role`. Where a
technical term is the honest one — `VLAN`, `DHCP`, `SOCKS5` — use it plainly
rather than inventing a friendlier word nobody else uses.

**Numbers and units are half-width, with a space**: `12 devices`, `443 ms`,
`8 MB`. A count of one still reads as a count: `1 device`.

**No em dash inside a sentence.** `The saved login is gone; enter it again`,
never `The saved login is gone — enter it again`. As a plain separator
between two values it is fine — `5 GHz — faster, shorter range`, a `—`
placeholder for a missing reading — the ban is on splicing prose with it.

**States, not mechanics; progress, not sentences.** A surface says where a
thing stands (`mounting…`, `shared`), never how the system will get there
(`the machine answers on its next heartbeat`). While something is under way
the control that asked shows it is busy; when it lands, the row itself is
the answer, and no `done` sentence follows it.

**Never announce what the product does not do.** `The password stays on this
machine; the hub is never told it` explains an implementation boundary
nobody asked about. Security properties live in `docs/`; the surface shows
the controls that exist and omits the reassurance. The same rule covers a
mode or an option: `Server: routes nothing, answers on the port it is
reached on` tells the reader two things it does not do. `Server: serves on
the networks it is connected to` tells them what it does.

## Sentences that are deleted on sight

A sentence of any of these shapes is deleted, or rewritten into one of the
shapes above. Each reads as an assistant talking, and the reader came to a
switch, not to a conversation.

| Shape | Example | What replaces it |
| --- | --- | --- |
| A label with a clause about where or how | `The language the panel uses; the terminal stays English` | the label alone: `Language` |
| A fact the reader needs for no decision | `A certificate is generated whether or not this is on` | nothing |
| A comment on the question itself | `Skipping is also an answer` | nothing |
| A description of the mechanism under the control | `Keys are sent straight to the machine`, `The grid fills as machines start talking to the gateway` | nothing, or the state the surface can show |
| A reassurance or a nudge | `Do not worry, this can be changed later` | nothing |
| What the thing does not do | `Does no routing` | what it does |

A description that says what the control does stays, cut to the one
sentence that says it; a second sentence stays only when it names a
consequence the reader decides on. What goes is the sentence that says
nothing about function: the mechanism, the comment, the reassurance, the
negation. An apply bar's hint, which says what applying does (`Reloads the
firewall and rebuilds the uplink routes.`), is such a sentence of function
and stays.

**A catalog change is reviewed as a table before it lands**: file, key, the
text as it is, and the text it becomes or `deleted`. Both languages change in
the same table.

## Names that are fixed

A fixed name is spelled one way on every surface: the panel, the desktop
client, the Android app, the docs and the release notes. Each language has
its own word, and a string in one language carries no word of the other.

| Thing | English | Chinese | Rule |
| --- | --- | --- | --- |
| the hub | hub, this hub | 中枢，这台中枢 | English never writes 中枢 and Chinese never writes `hub`. Neither calls the hub a gateway (网关): that word names the AI gateway, the side gateway mode and a network's router. |
| the product | Neutrino | 微子 | Neutrino is described as remote access to a person's own machines (远程访问). No surface calls it a VPN or a proxy (代理, 翻墙); the proxy is one feature, named on its own page. |
| the page of the ways in | **Access** | **外部访问** | The page, its sidebar entry and every link to it use this name. The configuration, the routes and the protocol keep `overlay`, and so do the catalog keys (`ui.nav.overlay`, `ui.overlay.*`). |
| the way in through the person's own server | SSH relay | SSH 中继 | The card, the section, the client's hub row and the docs use it; a sentence that names it again may say "the relay" (中继). The server it reaches is "your server" (你的服务器) in a label and VPS in the guide. The client's word, `reached_through`, is `ssh_relay`; the configuration, routes and codes keep `relay`. |
| the two frp vendors | SakuraFrp, OpenFrp | SakuraFrp，OpenFrp | Spelled as each vendor spells itself, in both languages; never 樱花 or a shortened name. The program both run is frpc, and a sentence about the tunnel says "tunnel" (隧道). |
| the page of the managed machines | **Agents** | **被控端** | The page, its sidebar entry in the hub group, the header chip and the Overview card use this name, and the sidebar's machine group below carries the same word. The routes keep `device` (`/api/hub/device`) and the catalog keys keep `devices`; the panel's address is `/agents`. |
| a managed machine's page | the machine page | 机器页 | Each machine's own page, `/agents/<id>`, which holds its modules; the panel has no Modules, Terminals or Files page. |

The sidebar's lines under the renamed entries, the Agents page's among them in "The Agents page's words":

| Key | English | Chinese |
| --- | --- | --- |
| `ui.nav.overlay`, `ui.overlay.title` | Access | 外部访问 |
| `ui.overlay.apply_engine`, the engine panel's apply bar | Apply access | 应用外部访问 |
| `ui.nav.overlay_description` | Reaching this hub from outside | 从外面连回这台中枢 |
| `ui.overlay.join_step_network`, `ui.overlay.join_step_peer`, `ui.overlay.join_step_key` | In the console, open Setup Keys and create a key. Make the key reusable with no usage limit, so every client of this hub can join with it. Copy the key it shows once and paste it below. | 在控制台里打开 Setup Keys，新建一把 key。把它设成可重复使用（reusable）、不限使用次数，这台中枢的每个客户端都用它加入。复制它只显示一次的 key，粘贴到下面。 |

A docs page follows this table where the term list in
[doc-author](../../doc-author/SKILL.md) offers a choice.

A module's title on the panel is the catalog's `ui.module_title.<name>`
when the catalog has it, and the manifest's `title` otherwise. A module
named after its product has no catalog entry and reads the same in both
languages, unless its publisher names it in Chinese: SiYuan is 思源笔记.

| Manifest name | English | Chinese |
| --- | --- | --- |
| `samba` | File share | 文件共享 |
| `terminal` | Terminal | 终端 |
| `remote_desktop` | Remote desktop | 远程桌面 |
| `podman` | Containers | 容器 |
| `zfs` | ZFS storage | ZFS 存储 |
| `gitea` | Gitea | Gitea |
| `vscode` | VS Code | VS Code |
| `code_server` | code-server | code-server |
| `cloudcli` | CloudCLI | CloudCLI |
| `codeg` | Codeg | Codeg |
| `hermes_webui` | Hermes WebUI | Hermes WebUI |
| `ayakaleaf` | Ayakaleaf | Ayakaleaf |
| `siyuan` | SiYuan | 思源笔记 |
| `cc_switch` | cc-switch | cc-switch |

## Software the owner installs

Gitea, VS Code, code-server, CloudCLI, Codeg, SiYuan, Hermes WebUI and
Ayakaleaf are programs the machine's owner installs on their own machine through a module. The text
rules follow from that:

| Rule | Example |
| --- | --- |
| A module page that names third-party software says that the owner installs it on that machine. | `You install VS Code Server on this machine under Microsoft's license terms.` |
| A module page names the publisher's terms only where the publisher asks for acceptance; VS Code is the one such module ([ui_behavior.md](ui_behavior.md), "Terms before a module opens"). CloudCLI's, Codeg's and SiYuan's pages carry no licence line. | |
| No surface says the hub downloads, provides, bundles or distributes third-party software, in either language (代为下载, 提供, 自带). A sentence about the mechanism, in a standard page or a code comment, makes the module's installer its subject. | `The module's installer fetches the archive.`, never `The hub downloads VS Code.` |
| The **About** card on the Settings page credits only the components the hub's own package carries on that system and in that edition, such as xray, CLIProxyAPI, NetBird, EasyTier, frp and tun2socks. Gitea, VS Code, code-server, CloudCLI, Codeg, SiYuan, Hermes WebUI and Ayakaleaf are never on it. | |

The VS Code notice and its button:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.vscode.terms_notice` | You install VS Code Server on this machine under Microsoft's license terms. Open them to accept them and use VS Code here. | 你在这台机器上按微软的许可条款安装 VS Code Server。打开条款即接受，之后才能在这里使用 VS Code。 |
| `ui.vscode.terms_accept` | Open and accept the terms | 打开并接受条款 |
| `ui.vscode.terms_accepted` | Terms accepted | 已接受条款 |

## The Agents page's words

The hub group's page of managed machines is **Agents** in English and
**被控端** in Chinese, the word every surface already uses for an agent
([ui_behavior.md](ui_behavior.md), "The Agents page"). Every key that named
that page, its count or its sidebar entry as a device changes with it:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.nav.devices`, `ui.devices.title` | Agents | 被控端 |
| `ui.nav.devices_description` | Managed machines and what you do with them | 被管理的机器和对它们的操作 |
| `ui.shell.chip_devices`, the header chip's label | agents | 被控端 |
| `ui.dashboard.tile_devices`, the Overview card, which links to `/agents` | Agents | 被控端 |
| `ui.devices.badge`, beside the title | {total} agents, {online} online | {total} 台被控端，{online} 台在线 |
| `ui.usage.device_row`, a usage row of a machine's key | agent {device} | 被控端 {device} |
| `ui.settings.update_confirm_body`, `ui.settings.update_confirm_body_installer` | The panel restarts, and agents on an older protocol need Reinstall on their machine page. If {version} does not answer within three minutes, {from} is put back. | 面板会重启，协议更旧的被控端要在各自的机器页上重新安装。{version} 三分钟内没有应答时，会装回 {from}。 |
| `ui.device_pick.no_devices_hint` | Add a machine on the Agents page. | 到“被控端”页添加一台机器。 |
| `ui.clients.filter_no_devices` | No agents yet. | 还没有被控端。 |
| `ui.nav.services_description` | What the hub publishes to clients | 中枢向客户端发布的内容 |

`ui.zfs.detail_device` names a disk's device and stays 设备. The keys of the
LAN scan and of unmanaged devices, `ui.devices.scan`, `ui.devices.scanning`,
`ui.devices.add_by_address`, `ui.devices.search_placeholder`,
`ui.devices.none_title`, `ui.devices.none_hint`, `ui.devices.managed_*`,
`ui.devices.unmanaged_*` and `ui.devices.filtered_*`, go with the scan; the
**Add over SSH** button is `ui.devices.add_by_ssh`, **Add over SSH** / **用
SSH 添加**. `ui.services.source_device` goes with the Services page's
sources: an app's source is `ui.app_source.module`, `ui.app_source.declared`
or `ui.app_source.manual`. `ui.device_chip_strip.label` goes with the
Terminals and Files pages, the only pages that drew the strip.

## The Clients page's words

[ui_behavior.md](ui_behavior.md), "The Clients page", places them. The keys
are in `locales/<language>/devices.json` beside the page's other
`ui.clients.*` keys. A kind's name is its `ui.clients.kind_<kind>`, and in
Chinese a kind is 权限, as in 默认权限.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.clients.fine_mode` | Choose per app | 逐个应用选择 |
| `ui.clients.fine_mode_description` | Whether each app, share, desktop and machine has a switch of its own under its kind. A switch set here wins over its kind. | 是否在每种权限下给每个应用、共享、桌面和机器单独一个开关。这里设的开关优先于所属权限。 |
| `ui.clients.follow_kind` | Follow the kind | 跟随所属权限 |
| `ui.clients.fine_mode_clear_warning` | The switches set per app are cleared. | 逐个应用设的开关会全部清除。 |
| `ui.clients.rows_empty` | None yet | 暂时没有 |
| `ui.clients.generate_link`, the link dialog's foot, in place of `ui.clients.create_link` | Generate link | 生成链接 |
| `ui.clients.done` | Done | 完成 |
| `ui.clients.waiting` | Waiting to join ({minutes} min left) | 等待加入（还剩 {minutes} 分钟） |
| `ui.clients.waiting_delete_body` | Its link stops working. | 它的链接随即失效。 |
| `ui.devices.generate_link`, the **Add by link** dialog's foot | Generate link | 生成链接 |
| `ui.devices.link_name_hint` | Left empty, the machine's host name names it. | 留空时用机器的主机名。 |
| `ui.clients.panel_clients`, `ui.web_shares.title`, the two panels | Clients, Web shares | 客户端、Web 分享 |
| `ui.web_shares.new_link` | New Web share link | 新建 Web 分享链接 |
| `ui.web_shares.share`, on a Services page row | Share | 分享 |
| `ui.web_shares.field_name`, `field_app`, `field_expires`, `field_site` | Name, App, Expires, Site | 名称、应用、有效期、站点 |
| `ui.web_shares.expires_1d`, `expires_7d`, `expires_30d`, `until_revoked` | 1 day, 7 days, 30 days, Until revoked | 1 天、7 天、30 天、直到撤销 |
| `ui.web_shares.site_other`, `site_other_hint` | Another site; The https:// address of your own copy of the page. | 其他站点；你自己托管的那份页面的 https:// 地址。 |
| `ui.web_shares.link_once` | Anyone with this link opens this app until the share ends. Copy it now: the hub cannot show it again. | 拿到这个链接的人都能打开这个应用，直到分享结束。现在就复制：中枢之后无法再显示它。 |
| `ui.web_shares.run_account_warning`, under **App** for an app that signs visitors in as the account it runs as | Visitors use this app as {account}: they can do whatever the app lets that account do, until the link expires or is revoked. | 访客会以 {account} 的身份使用这个应用：在链接过期或撤销前，能做这个应用允许该账户做的一切。 |
| `ui.web_shares.guest_hint` | Visitors sign in as this account. Invite this address inside the app to give them a project. | 访客以这个账户登录。在应用里邀请这个地址，访客就能看到对应的项目。 |
| `ui.web_shares.expires_in` | Expires in {days} d | {days} 天后到期 |
| `ui.web_shares.online`, the share's open pages | {count} online | 在线 {count} |
| `state.share_active`, `state.share_preparing`, `state.share_unavailable`, `state.share_failed` | active, preparing, unavailable, failed | 可用、准备中、暂不可用、失败 |
| `ui.web_shares.revoke` | Revoke | 撤销 |
| `ui.web_shares.revoke_title` | Revoke {name} | 撤销 {name} |
| `ui.web_shares.revoke_body` | Every page open on this share closes, and its link stops working. | 这个分享上打开着的页面全部关闭，链接随即失效。 |
| `ui.web_shares.revoke_guest` | The guest account {email} is removed from the app; what it edited in your projects stays. | 应用里的访客账户 {email} 会删除；它在你的项目里改过的内容保留。 |
| `ui.web_shares.empty`, `ui.web_shares.empty_hint` | No Web shares; Share one app's page with people who have no client. | 还没有 Web 分享；把一个应用的页面分享给没有客户端的人。 |
| `code.share_unknown` | This share no longer exists. | 这个分享已不存在。 |
| `code.web_share_entry_invalid` | This app's page cannot be shared. | 非法应用：这个应用的页面不能分享。 |
| `code.web_share_site_invalid` | {site} is not an https:// address. | 非法站点：{site} 不是 https:// 地址。 |
| `code.web_share_unknown` | This share no longer exists. | 这个分享已不存在。 |

## The Credentials page's words

[ui_behavior.md](ui_behavior.md), "The Credentials page", places them. The
keys are in `locales/<language>/devices.json` beside the page's other `ui.credentials.*` keys, and the codes in
`codes.json`.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.credentials.generated_title` | Generated by the hub | 中枢生成的 |
| `ui.credentials.generated_hint` | Passwords and keys the hub made for your machines. Clients receive them by themselves; you need one to sign in by hand. | 中枢为你的机器生成的密码和钥匙。客户端会自己取用，手动登录时才需要它们。 |
| `ui.credentials.smb_password` | SMB password · {account} | SMB 密码 · {account} |
| `ui.credentials.seat_password` | Remote desktop password | 远程桌面密码 |
| `ui.credentials.ssh_key` | SSH key · {account} | SSH 钥匙 · {account} |
| `ui.credentials.reveal`, `ui.credentials.hide`, `ui.credentials.copy`, `ui.credentials.rotate` | Reveal, Hide, Copy, Rotate | 显示、隐藏、复制、轮换 |
| `ui.credentials.rotate_title` | Rotate {name} | 轮换{name} |
| `ui.credentials.rotate_smb_body` | The share takes the new password at once. Clients use it at their next mount; a mount made by hand with the old one stops working. | 共享立即改用新密码。客户端下次挂载时自动用新密码；手动用旧密码挂载的会失效。 |
| `ui.credentials.rotate_seat_body` | Every viewer is disconnected, and clients use the new password at their next connection. | 所有正在看的人都会断开，客户端下次连接时用新密码。 |
| `ui.credentials.rotate_ssh_body` | The machine stops accepting the old key. Clients fetch the new one by themselves; a copy of the old key elsewhere stops working. | 机器不再接受旧钥匙。客户端会自己取新钥匙；别处留着的旧钥匙副本随即失效。 |
| `ui.credentials.generated_empty` | No generated secrets yet | 还没有中枢生成的密钥 |
| `code.generated_credential_unknown` | The machine no longer has this secret. | 这台机器已没有这个密钥。 |

## The Web share page's words

The page a Web share link opens ([web_share.md](web_share.md), "The
screens") carries its words in `shell.js`, in the language the browser
names: Chinese when it starts with `zh`, English otherwise. `<app>` is the
link's `app.title`.

| Screen | English | Chinese |
| --- | --- | --- |
| Loading | Opening <app>… | 正在打开 <app>… |
| The link no longer works | This link is no longer valid. / Ask the person who shared it for a new one. | 这个链接已失效。/ 请向分享给你的人要一个新链接。 |
| The hub is offline | The hub is offline. / The computer that shares this app cannot be reached right now. | 中枢已离线。/ 分享这个应用的电脑现在连不上。 |
| The machine is offline | This machine is offline. / The app's machine is not connected to its hub right now. | 这台机器已离线。/ 这个应用所在的机器现在没有连上它的中枢。 |

## The machine page's words

The machine page's sections, the available accounts, the catalog and a
module's version line ([ui_behavior.md](ui_behavior.md), "The machine
page"). The model pickers follow the desktop client's words for its AI page
where they fit.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.machine.agent_version` | Agent v{version} | 被控端 v{version} |
| `ui.machine.monitor` | Monitor | 监控 |
| `ui.machine.modules` | Modules | 模块 |
| `ui.machine.agent` | The agent | 被控端本身 |
| `ui.machine.agent_update` | Update agent | 更新被控端 |
| `ui.machine.agent_reinstall` | Reinstall | 重新安装 |
| `ui.accounts.title` | Available accounts | 可用账户 |
| `ui.accounts.empty` | No account added yet. | 还没有添加账户。 |
| `ui.accounts.empty_hint` | Add the accounts of this machine its terminal, files and programs run as. | 添加这台机器上的账户，终端、文件和各个程序都以这些账户运行。 |
| `ui.accounts.add` | Add | 添加 |
| `ui.accounts.system_account` | System account | 系统账户 |
| `ui.accounts.password` | Password | 密码 |
| `ui.accounts.password_hint` | Windows signs this account in with it for every feature. | Windows 的各项功能都用它登录这个账户。 |
| `ui.accounts.share_path` | Share path | 文件共享路径 |
| `ui.accounts.shell` | Shell | 默认 shell |
| `ui.accounts.ai_tools` | AI tools use the hub's gateway | AI 工具走中枢网关 |
| `ui.accounts.edit`, `ui.accounts.remove` | Edit, Remove | 编辑、移除 |
| `ui.accounts.remove_title` | Remove {account} | 移除 {account} |
| `ui.accounts.remove_body` | {modules} stop running as {account}, and its AI tools go back to their own settings. | {modules} 不再以 {account} 运行，它的 AI 工具改回原来的设置。 |
| `ui.accounts.remove_body_none` | {account} leaves this machine's accounts, and its AI tools go back to their own settings. | {account} 从这台机器的可用账户里移除，它的 AI 工具改回原来的设置。 |
| `ui.machine.version`, `ui.machine.platform`, `ui.machine.hostname`, `ui.machine.last_report` | Version, Platform, Host name, Last report | 版本、平台、主机名、最后上报 |
| `ui.machine.uptime`, `ui.machine.load`, `ui.machine.disk`, `ui.machine.temperature` | Uptime, Load 1/5/15 min, Disk, Temperature | 运行时间、负载 1/5/15 分钟、磁盘、温度 |
| `ui.machine.not_found` | This machine is not on record. | 没有这台机器的记录。 |
| `ui.ai_tools.gateway_default` | Gateway default | 网关默认 |
| `ui.modules.tabs_title` | Module configuration | 模块配置 |
| `ui.modules.log_title` | Log · last 200 lines | 日志 · 最后 200 行 |
| `ui.modules.config_title` | Configuration | 配置 |
| `ui.modules.enabled_accounts` | Enabled accounts | 启用的账户 |
| `ui.modules.no_accounts` | Add an account under Available accounts first. | 先在“可用账户”里添加账户。 |
| `ui.samba.replace_notice` | Applying replaces this machine's smb.conf. The old file is kept as /etc/samba/smb.conf.before_neutrino. | 应用会替换这台机器的 smb.conf，原文件保存为 /etc/samba/smb.conf.before_neutrino。 |
| `ui.samba.home_shares`, `ui.samba.folder_shares`, the File share tab's two panels | Home shares, Folder shares | Home 共享、文件夹共享 |
| `ui.samba.home_shares_hint` | One share for each checked account, named after it, at its share path. | 每个勾选的账户一个共享，以账户命名，位置是它的文件共享路径。 |
| `ui.samba.folder_shares_hint` | A folder you name, shared with the accounts you check. Each account's files are written as that account. | 你命名的一个文件夹，共享给勾选的账户。每个账户写入的文件都归它自己。 |
| `ui.samba.folder_add` | Add | 添加 |
| `ui.samba.folder_name`, `ui.samba.folder_path`, `ui.samba.folder_accounts` | Name, Folder, Accounts | 名称、文件夹、账户 |
| `ui.samba.folder_edit`, `ui.samba.folder_remove` | Edit, Remove | 编辑、移除 |
| `ui.samba.folder_remove_title` | Remove {name} | 移除 {name} |
| `ui.samba.folder_remove_body` | The share goes away. The folder {path} and its files stay. | 共享会移除，文件夹 {path} 和里面的文件都保留。 |
| `ui.samba.folder_empty` | No folder shares yet. | 还没有文件夹共享。 |
| `ui.samba.folder_no_accounts` | Enable an account under Home shares first. | 先在“Home 共享”里启用账户。 |
| `code.share_name_invalid` | {name} cannot name a share: use 1 to 64 letters, digits, -, _ and ., other than global, homes and printers. | {name} 不能用作共享名：只能用 1 到 64 个字母、数字、-、_ 和 .，也不能是 global、homes 或 printers。 |
| `code.share_account_not_enabled` | {account} is not enabled for this machine's file share. | 这台机器的文件共享没有启用 {account}。 |
| `code.folder_share_unknown` | This machine has no folder share named {name}. | 这台机器没有叫 {name} 的文件夹共享。 |
| `ui.modules.add_module` | + Add module | + 添加模块 |
| `ui.module_catalog.title` | Add module | 添加模块 |
| `ui.module_catalog.search` | Search names and descriptions | 搜索名称或说明 |
| `ui.module_catalog.close` | Close | 关闭 |
| `ui.module_catalog.category_all`, `_code`, `_paper`, `_lab`, `_design`, `_notes`, `_files`, `_remote`, `_other` | All, Coding, Writing papers, Experiments, Design and creation, Notes, Files, Remote desktop, Other | 全部、写代码、写论文、跑实验、设计与创作、笔记、文件、远程桌面、其它 |
| `ui.module_catalog.<module>` | one line on the module, in each language | |
| `ui.ssh_server.host_key` | Host key {fingerprint} | 主机密钥 {fingerprint} |
| `ui.ssh_server.apply` | Apply SSH server | 应用 SSH 服务器 |
| `state.queued` | queued | 排队中 |
| `state.install_failed`, and `ui.module_state.install_failed` on a machine chip | install failed | 安装失败 |
| `state.ai_tools_switched` | Uses the hub's AI gateway | 使用中枢的 AI 网关 |
| `state.ai_tools_switched_back` | Uses its own settings | 使用自己原来的设置 |
| `ui.ai_tools.switch_back_failed`, an account `failed` with `switch_failed` while its switch is off | cc-switch did not put the tools back to their own settings: {detail} | cc-switch 没能把工具改回原来的设置：{detail} |
| `ui.ai_tools.tool_claude`, `ui.ai_tools.tool_codex`, `ui.ai_tools.tool_gemini` | Claude Code, Codex, Gemini | Claude Code、Codex、Gemini |
| `ui.ai_tools.slot_default`, `ui.ai_tools.slot_opus`, `ui.ai_tools.slot_sonnet`, `ui.ai_tools.slot_haiku` | Default model, Opus slot, Sonnet slot, Haiku slot | 默认模型、Opus 档位、Sonnet 档位、Haiku 档位 |
| `ui.ai_tools.codex_effort` | Reasoning effort | 推理强度 |
| `code.gateway_not_serving` | The hub's AI gateway serves no model yet; set it up on the AI page first. | 中枢的 AI 网关还没有可用的模型，先到 AI 页设置好。 |
| `code.zfs_kernel_module_missing`, on an `absent` ZFS storage tab | The running kernel {kernel} has no ZFS module; install the module again. | 正在运行的内核 {kernel} 没有 ZFS 模块，重新安装这个模块。 |
| `ui.modules.version_installed` | Installed {version} | 已安装 {version} |
| `ui.modules.version_newest` | newest {version} | 最新 {version} |
| `ui.modules.update` | Update | 更新 |
| `ui.modules.install_version` | Install another version… | 安装另一个版本… |
| `ui.modules.version_tested` | tested | 已测试 |
| `ui.modules.version_untested` | untested | 未测试 |
| `ui.modules.version_follow_tested` | Follow the tested version | 跟随已测试的版本 |
| `ui.modules.downgrade_title` | Install {module} {version}? | 安装 {module} {version}？ |
| `ui.modules.downgrade_body` | {module} moves its data forward when it starts on a newer version, and {version} is older than the one installed, so it can fail to read that data. | {module} 换到新版本启动时会把数据往前迁移，{version} 比装着的版本旧，可能读不了这些数据。 |
| `code.download_failed` | No source served {file}: {sources} | 没有来源能提供 {file}：{sources} |
| `code.version_switch_failed` | Version {version} did not start, so the previous version runs again: {detail} | 版本 {version} 没能启动，已换回原来的版本：{detail} |
| `code.version_unknown` | Version {version} is not listed for this machine. | 这台机器没有版本 {version}。 |
| `code.version_locked` | The version of {module} follows the system or the agent and cannot be chosen. | {module} 的版本跟随系统或被控端，不能选择。 |

The keys of the Modules page's machine picker and **Global configuration**,
`ui.modules.no_pick`, `ui.modules.no_pick_hint`, `ui.modules.global_title`,
`ui.modules.no_instances`, `ui.ai_tools.title`, `ui.ai_tools.use`,
`ui.ai_tools.accounts` and `ui.ai_tools.no_accounts`, go with them.
**Configure** is `ui.modules.configure` and its closing word
`ui.modules.configure_close`, the page's existing words. The desktop
client's reason for its disabled AI page and the code its command line
refuses with:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.reason.ai_managed`, `code.ai_tools_managed` | This is an agent's machine: set its AI tools on the hub's panel, in the account's form on its machine page. | 这是被控端所在的机器，请到中枢面板上这台机器的机器页，在账户的表单里设置它的 AI 工具。 |

## The uninstall dialog's words

Every module's **Uninstall** opens one dialog ([ui_behavior.md](ui_behavior.md),
"The machine page"). Its title, body and button are catalog keys in
`locales/<language>/modules.json`; `ui.modules.uninstall_body_data` goes.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.modules.uninstall_title` | Uninstall {module} from {device} | 从 {device} 卸载 {module} |
| `ui.modules.uninstall_body` | The module's programs, its services and the configuration the hub wrote are removed. | 模块的程序、服务和中枢写下的配置都会移除。 |
| `ui.modules.uninstall` | Uninstall | 卸载 |

The line under the body is the module's own, kept in `uninstall_data` of
its manifest and not in the catalog
([agent/module_install.md](agent/module_install.md), "The manifest").
`{data_dir}` is the per-account data directory the hub writes in for the
machine's system.

| Module | Deleted | English | Chinese |
| --- | --- | --- | --- |
| `samba` | no | The shared folders and the files in them stay where they are. | 共享的文件夹和里面的文件都原样保留。 |
| `podman` | no | The declared containers' volumes stay, and on Windows and macOS so does the Podman machine. | 声明的容器的卷都保留，Windows 和 macOS 上的 Podman 虚拟机也保留。 |
| `zfs` | no | The pools and their datasets stay on their disks. | 存储池和其中的数据集都留在磁盘上。 |
| `gitea` | no | The repositories, Gitea's accounts and its database stay in its data directory. | 仓库、Gitea 的账户和数据库都留在它的数据目录里。 |
| `vscode` | no | Each account's settings and extensions stay in its home folder. | 每个账户的设置和扩展都留在它的主目录里。 |
| `code_server` | no | Each account's code-server settings and extensions stay in its home folder. | 每个账户的 code-server 设置和扩展都留在它的主目录里。 |
| `cloudcli` | no | Each account's CloudCLI data stays in {data_dir}. | 每个账户的 CloudCLI 数据留在 {data_dir}。 |
| `codeg` | no | Each account's Codeg data stays in {data_dir}. | 每个账户的 Codeg 数据留在 {data_dir}。 |
| `siyuan` | no | Each account's notes stay in {data_dir}. | 每个账户的笔记留在 {data_dir}。 |
| `hermes_webui` | yes | The conversations, settings and workspace files are deleted and cannot be recovered. | 对话、设置和工作区里的文件都会删除，无法恢复。 |
| `ayakaleaf` | yes | The papers and projects are deleted and cannot be recovered. | 论文和项目都会删除，无法恢复。 |

## The Terminal and Remote desktop tabs' words

The tabs' names are the module titles of "Names that are fixed":
**Terminal** and **Remote desktop** in English, **终端** and **远程桌面** in
Chinese. The Terminal tab's panel is its enabled accounts, each row with the
account's shell; `ui.terminal_module.account`, `account_agent`,
`account_windows`, `shell_path`, `shell_path_hint` and `browse` go with the
account and the shell program it set before.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.terminal_module.apply` | Apply terminal | 应用终端设置 |
| `ui.terminal_module.apply_hint` | Terminals opened from now on use these; open ones keep what they run. | 之后打开的终端用这些设置，已打开的不变。 |
| `ui.remote_desktop_module.switch` | Share this machine's desktop | 共享这台机器的桌面 |
| `ui.remote_desktop_module.switch_hint` | Whether this machine runs the agent's RustDesk for this hub's clients. Turning it on stops every other RustDesk host on the machine; turning it off puts back what was there. | 是否让这台机器运行被控端自带的 RustDesk，供这台中枢的客户端连接。打开时会停掉机器上其它的 RustDesk 主机，关闭时还原原来的。 |
| `ui.remote_desktop_module.apply` | Apply remote desktop | 应用远程桌面 |
| `ui.remote_desktop_module.apply_hint` | Starts or stops sharing this desktop now. | 立即开始或停止共享这个桌面。 |
| `code.shell_program_unusable` | {path} is not a program this machine can run. | {path} 不是这台机器能运行的程序。 |
| `code.rdp_takeover_failed` | Remote desktop could not start at {step}: {detail} | 远程桌面在 {step} 这一步没能启动：{detail} |
| `code.rdp_restore_failed` | Remote desktop could not put back the machine's RustDesk at {step}: {detail} | 远程桌面在 {step} 这一步没能还原机器原来的 RustDesk：{detail} |

## The Hermes WebUI tab's words

[ui_behavior.md](ui_behavior.md), "The machine page", places them. The keys
are in `locales/<language>/modules.json`. The tab has no panel, since the
agent takes its port, so `ui.hermes_webui.port`, `port_hint`, `apply` and
`apply_hint` go.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.hermes_webui.owner_notice` | You install Hermes WebUI and Hermes Agent, both MIT-licensed, on this machine. | 你在这台机器上安装 Hermes WebUI 和 Hermes Agent，两者都以 MIT 许可发布。 |
| `ui.hermes_webui.owner_notice_version` | You install Hermes WebUI and Hermes Agent, both MIT-licensed, on this machine. Installed: {version}. | 你在这台机器上安装 Hermes WebUI 和 Hermes Agent，两者都以 MIT 许可发布。已安装：{version}。 |

## The Ayakaleaf tab's words

[ui_behavior.md](ui_behavior.md), "The machine page", places them. The keys
are in `locales/<language>/modules.json`, and the code's in `codes.json`.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.ayakaleaf.owner_notice` | You install Ayakaleaf, MongoDB and Redis on this machine, each under its publisher's license. | 你在这台机器上安装 Ayakaleaf、MongoDB 和 Redis，各自遵循发布者的许可证。 |
| `ui.ayakaleaf.model` | AI model | AI 模型 |
| `ui.ayakaleaf.model_hint` | The model the editor's AI assistant uses. | 编辑器里的 AI 助手用这个模型。 |
| `ui.ayakaleaf.apply` | Apply Ayakaleaf | 应用 Ayakaleaf 设置 |
| `ui.ayakaleaf.apply_warning` | Ayakaleaf restarts, and open editors connect again. | Ayakaleaf 会重启，打开着的编辑器会重新连接。 |
| `code.ayakaleaf_setup_failed` | Ayakaleaf's first start stopped at {step}: {detail} | Ayakaleaf 首次启动停在 {step} 这一步：{detail} |
| `code.ayakaleaf_guest_failed`, under a Web share's row | Ayakaleaf could not make the guest account at {step}: {detail} | Ayakaleaf 在 {step} 这一步没能建好访客账户：{detail} |

## The Containers tab's words

The Run settings, the container editor's **Services** row, the restart
notice and the codes Containers adds. [ui_behavior.md](ui_behavior.md),
"The machine page", places them. The `ui.*` keys are in
`locales/<language>/modules.json` and the `code.*` keys in `codes.json`;
the agent's `cli/wording.py` words the same codes in English.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.containers.run_title` | Run settings | 运行设置 |
| `ui.containers.run_account` | Account | 账户 |
| `ui.containers.run_account_hint` | The available account whose Podman machine runs the containers; on Windows it starts at boot with the account's login. | 用这个可用账户的 Podman 虚拟机运行容器；Windows 上开机时用这个账户的登录启动。 |
| `ui.containers.run_cpus` | CPUs | CPU 数 |
| `ui.containers.run_memory` | Memory (GiB) | 内存（GiB） |
| `ui.containers.run_disk` | Disk limit (GiB) | 磁盘上限（GiB） |
| `ui.containers.run_default_hint` | 0 uses Podman's default: half the CPUs, 2 GiB of memory, a 100 GiB disk. | 填 0 用 Podman 的默认值：一半的 CPU、2 GiB 内存、100 GiB 磁盘。 |
| `ui.containers.run_default_hint_windows` | A 0 for CPUs or memory uses Podman's default: half the CPUs, 2 GiB of memory. | CPU 数或内存填 0 用 Podman 的默认值：一半的 CPU、2 GiB 内存。 |
| `ui.containers.run_disk_hint` | The disk only grows. It is {current} GiB now. | 磁盘只能改大，现在是 {current} GiB。 |
| `ui.containers.run_apply` | Apply run settings | 应用运行设置 |
| `ui.containers.run_apply_hint` | Starts this account's Podman machine, and creates it the first time. | 启动这个账户的 Podman 虚拟机，第一次会先新建。 |
| `ui.containers.run_restart_warning` | The machine restarts, and its containers stop for a moment. | 虚拟机会重启，容器会停一会儿。 |
| `ui.containers.run_wsl_warning` | Every WSL system of this account restarts with the new settings. | 这个账户下的所有 WSL 系统都会重启并使用新设置。 |
| `ui.containers.run_account_warning` | The old account's machine stops; its images and named volumes stay there. | 旧账户的虚拟机会停下，里面的镜像和命名卷留在原处。 |
| `ui.containers.run_needed` | Choose an account under Run settings first. | 先在“运行设置”里选一个账户。 |
| `ui.containers.browse` | Browse… | 浏览… |
| `ui.containers.volume_placeholder_linux`, `ui.containers.volume_placeholder_windows`, `ui.containers.volume_placeholder_darwin` | `/srv/share:/data`, `C:\data:/data`, `/Users/me/data:/data` | `/srv/share:/data`、`C:\data:/data`、`/Users/me/data:/data` |
| `ui.containers.services` | Services | 服务 |
| `ui.containers.service_auto`, `ui.containers.service_web`, `ui.containers.service_port` | Auto, Web, Port | 自动、网页、端口 |
| `ui.containers.service_http`, `ui.containers.service_https`, `ui.containers.service_tcp`, `ui.containers.service_udp` | http, https, TCP, UDP | http、https、TCP、UDP |
| `ui.containers.service_detected` | Auto: {kind} detected | 自动：检测到 {kind} |
| `ui.containers.service_pending` | Auto: detected after the container starts | 自动：容器运行后检测 |
| `ui.containers.services_hint` | Each port is an entry of the container's app on the clients' Apps page, Web opening in the browser. | 每个端口都是这个容器在客户端“应用”页上的一个入口，网页入口会在浏览器里打开。 |
| `ui.containers.hub_title` | Hub containers | 中枢的容器 |
| `ui.containers.hub_hint` | The hub's modules run these. Change them in their module's tab. | 这些由中枢的模块运行，要改就到对应模块的标签页里改。 |
| `ui.containers.hub_empty` | No module runs a container on this machine. | 这台机器上还没有模块运行容器。 |
| `ui.containers.source_hub`, `ui.containers.source_declared`, `ui.containers.source_manual` | hub, declared, manual | 中枢、声明、手动 |
| `ui.modules.restart_now` | Restart now | 立即重启 |
| `ui.modules.restart_title` | Restart {device} | 重启 {device} |
| `ui.modules.restart_body` | The machine restarts now, and every program open on it closes. | 这台机器会立即重启，上面打开的程序都会关闭。 |
| `ui.modules.restart_confirm` | Restart | 重启 |
| `code.reboot_required` | Windows needs a restart to finish turning on WSL; the install goes on after it. | Windows 需要重启才能装好 WSL，重启后会接着安装。 |
| `code.service_protocol_none` | Port {port} needs TCP, UDP or both. | 端口 {port} 至少要勾选 TCP 或 UDP。 |
| `code.service_invalid` | The service on port {port} of {name} cannot be used: the port is not published, is listed twice, or has an unknown type or protocol. | 非法服务设置：容器 {name} 的端口 {port} 没有发布、重复列出，或类型、协议不在可选范围内。 |
| `code.volume_invalid` | The volume {volume} of {name} needs a folder or a volume name, a colon, and a path in the container. | 非法卷：容器 {name} 的卷 {volume} 要写成文件夹或卷名、冒号、容器里的路径。 |
| `code.container_unknown` | Podman has no container called {name}. | Podman 里没有叫 {name} 的容器。 |
| `code.container_name_invalid` | The container name {name} cannot be used; use up to 64 lowercase letters, digits, dashes and underscores, starting with a letter or a digit. | 非法容器名：{name}，只能用小写字母、数字、连字符和下划线，以字母或数字开头，最多 64 个字符。 |
| `code.container_name_duplicate` | Two containers are both named {name}. | 有两个容器都叫 {name}。 |
| `code.image_invalid` | The image tag of {name} is empty or holds a space. | 非法镜像：容器 {name} 的镜像标签为空或含空格。 |
| `code.port_mapping_invalid` | The port {port} of {name} needs a host port, a colon and a container port, such as 8080:80, with /udp after it for UDP. | 非法端口映射：容器 {name} 的端口 {port} 要写成主机端口、冒号、容器端口，例如 8080:80，UDP 在后面加 /udp。 |
| `code.environment_invalid` | The environment entry {entry} of {name} needs a name, an equals sign and a value, such as KEY=value. | 非法环境变量：容器 {name} 的 {entry} 要写成变量名、等号、值，例如 KEY=value。 |
| `code.command_invalid` | The command of {name} needs to fit on one line. | 非法命令：容器 {name} 的命令只能写在一行里。 |
| `code.mirror_invalid` | The mirror {mirror} needs a registry host, with an optional port and path and no http://, such as mirror.ccs.tencentyun.com. | 非法镜像源：{mirror} 要写成镜像仓库的主机名，可带端口和路径，不带 http://，例如 mirror.ccs.tencentyun.com。 |
| `code.windows_feature_failed` | Windows could not turn on {feature} (exit code {exit_code}). | Windows 没能打开 {feature}（退出码 {exit_code}）。 |
| `code.podman_install_failed` | The {artifact} installer failed (exit code {exit_code}). | {artifact} 安装包没能装上（退出码 {exit_code}）。 |
| `code.machine_account_missing` | Choose the account that runs the containers. | 选一个运行容器的账户。 |
| `code.machine_cpus_invalid` | CPUs must be between 0 and {max}. | 非法 CPU 数：要在 0 到 {max} 之间。 |
| `code.machine_memory_invalid` | Memory must be between 0 and {max} GiB. | 非法内存大小：要在 0 到 {max} GiB 之间。 |
| `code.machine_disk_shrink` | The disk is {current_gib} GiB and only grows; {disk_gib} GiB is smaller. | 磁盘现在是 {current_gib} GiB，只能改大，{disk_gib} GiB 比它小。 |
| `code.machine_disk_invalid` | The disk limit {disk_gib} GiB is not valid: on Windows it is 1 GiB or more. | 非法磁盘上限：Windows 上至少要 1 GiB，{disk_gib} GiB 不行。 |
| `code.volume_not_shared` | The volume {volume} of {name} is outside what the Podman machine shares: a fixed drive on Windows; /Users, /private or /var/folders on macOS. | 容器 {name} 的卷 {volume} 不在 Podman 虚拟机共享的范围内：Windows 上是本机的固定磁盘，macOS 上是 /Users、/private 或 /var/folders。 |
| `code.udp_not_forwarded` | Port {port} of {name} is UDP, and WSL forwards TCP alone; on Windows publish it on TCP. | 容器 {name} 的端口 {port} 是 UDP，而 WSL 只转发 TCP；在 Windows 上请用 TCP 发布。 |
| `code.machine_image_missing` | The Podman machine image is not on this machine; install the module again. | 这台机器上没有 Podman 虚拟机映像，重新安装这个模块。 |
| `code.machine_init_failed` | Podman could not create the machine: {detail} | Podman 没能新建虚拟机：{detail} |
| `code.machine_set_failed` | Podman could not change the machine: {detail} | Podman 没能修改虚拟机：{detail} |
| `code.machine_unreachable` | The Podman machine does not answer: {detail} | Podman 虚拟机没有响应：{detail} |
| `code.container_name_reserved` | The name {name} starts with neutrino_, which the hub keeps for the containers of its modules. | 容器名 {name} 以 neutrino_ 开头，这个前缀留给中枢模块的容器。 |
| `code.module_in_use` | {modules} run on Containers; uninstall them first. | {modules} 运行在容器模块上，先卸载它们。 |
| `code.container_hub_owned` | {name} is run by a module of the hub; change it in that module's tab. | {name} 由中枢的模块运行，要改就到那个模块的标签页里改。 |

## The Services page's health words

A declared row's state word, beside the still dot the page uses for no
opinion when the row holds no health:

| Key | English | Chinese | The row |
| --- | --- | --- | --- |
| `state.checking` | checking… | 检查中… | a TCP, web or file record the hub has not probed yet |
| `state.not_checked` | not checked | 未检查 | a record the hub never probes, a UDP port; and a record whose last probe could not judge it |

A UDP port record is in neither number of the page's badge, `{healthy} of
{total} healthy`, since the hub holds no health for it.

## The Network page's words

| Key | English | Chinese |
| --- | --- | --- |
| `ui.network.exposure_title` | Exposure | 开放范围 |
| `ui.network.exposure_hint` | The networks whose hosts reach the hub's own ports: the panel over HTTP and HTTPS, the connection port, DNS and the SOCKS ports. SSH and the other services the hub does not run are the system firewall's. | 哪些网段的主机能连到中枢自己的端口：面板的 HTTP 和 HTTPS、连接端口、DNS、SOCKS 端口。SSH 等不归中枢的服务由系统防火墙管。 |
| `ui.network.unsaved_interface` | New, not in use until turned on and applied | 新网口，打开并应用后才使用 |
| `ui.network.field_country_code` | Country code | 国家代码 |
| `ui.network.error_country_code` | Two letters, such as DE. 5 GHz needs one. | 两个字母，例如 CN。5 GHz 需要国家代码。 |

## Direct's words

| Key | English | Chinese |
| --- | --- | --- |
| `ui.overlay.direct_title` | Direct | 直连 |
| `ui.overlay.summary_direct` | Clients reach the hub's connection port at its own addresses | 客户端直接连中枢自己地址上的连接端口 |
| `ui.overlay.direct_switch_hint` | Whether the hub's connection port answers on every enabled interface. It opens that port, and no other, to every host that can reach those interfaces. | 是否在每个启用的网口上开放中枢的连接端口。只开放这一个端口，所有能连到这些网口的主机都能连上它。 |
| `ui.overlay.direct_public_host` | Public address | 公网地址 |
| `ui.overlay.direct_public_port` | Public port | 公网端口 |
| `ui.overlay.direct_public_host_hint` | A host name or IP address that reaches this hub from outside; leave it empty for none. | 从外面能连到这台中枢的主机名或 IP 地址；没有就留空。 |
| `ui.overlay.direct_addresses` | Addresses for clients | 客户端连接地址 |
| `ui.overlay.direct_addresses_empty` | No enabled interface has an address. | 没有哪个启用的网口有地址。 |
| `ui.overlay.direct_addresses_exposed` | Every enabled interface with an address is already exposed and answers on the connection port, so Direct adds none of them. A public address can still be set. | 每个有地址的启用网口都已开放，已经能连上连接端口，所以直连不再添加它们的地址。公网地址仍然可以设置。 |
| `ui.overlay.direct_apply` | Apply Direct | 应用直连 |
| `ui.overlay.direct_apply_hint` | Saves the public address and gives it to clients and agents. | 保存公网地址，并发给客户端和被控端。 |

A client's Hubs row names the way it reached the hub; `reached_through`
`direct` is `ui.through.direct`, **Direct** / **直连**.

## The relay's words

| Key | English | Chinese |
| --- | --- | --- |
| `ui.overlay.relay_title` | SSH relay | SSH 中继 |
| `ui.overlay.summary_relay` | Through a server you own, over SSH | 经你自己的服务器，用 SSH 转发 |
| `ui.overlay.relay_host` | Server | 服务器 |
| `ui.overlay.relay_ssh_port` | SSH port | SSH 端口 |
| `ui.overlay.relay_account` | Account | 账户 |
| `ui.overlay.relay_credential_hint` | How the hub signs in to your server. | 中枢用什么方式登录你的服务器。 |
| `ui.overlay.relay_public_port` | Public port | 对外端口 |
| `ui.overlay.relay_address` | Address for clients | 客户端连接地址 |
| `ui.overlay.relay_host_key` | Host key | 主机密钥 |
| `ui.overlay.relay_forget_host_key` | Forget host key | 忘记主机密钥 |
| `ui.overlay.relay_apply` | Apply SSH relay | 应用 SSH 中继 |
| `ui.overlay.relay_apply_hint` | Saves the SSH relay and connects it again. | 保存 SSH 中继设置并重新连接。 |
| `ui.overlay.relay_apply_warning` | Clients connected through the SSH relay disconnect and connect again. | 经 SSH 中继连着的客户端会断开再重连。 |

The credential's controls are the agent install's, with its words:
`ui.install_agent.credential` (**Credential** / **凭据**) choosing
`ui.install_agent.kind_key` (**SSH key**) or `ui.install_agent.kind_login`
(**Password** / **密码**), then the vault picker labelled
`ui.install_agent.key` with `ui.install_agent.key_hint`, or
`ui.install_agent.login` with `ui.install_agent.login_hint`.

The state words, `state.relay_<code>`:

| `state` | English | Chinese |
| --- | --- | --- |
| `disabled` | Off | 已关闭 |
| `not_configured` | Not configured | 未配置 |
| `vault_locked` | Vault locked | 保险库已锁定 |
| `connecting` | Connecting | 连接中 |
| `connected` | Connected | 已连上 |
| `port_closed` | Public port closed | 对外端口不通 |
| `auth_failed` | Authentication failed | 认证失败 |
| `host_key_changed` | Host key changed | 主机密钥已变 |
| `forward_refused` | Forward refused | 服务器不让对外监听 |
| `unreachable` | Server unreachable | 连不上服务器 |

## The frp cards' words

SakuraFrp's and OpenFrp's sections share the keys below; `{vendor}` is the
card's title. [ui_behavior.md](ui_behavior.md), "The cards on the Access
page", places them.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.overlay.sakurafrp_title` | SakuraFrp | SakuraFrp |
| `ui.overlay.openfrp_title` | OpenFrp | OpenFrp |
| `ui.overlay.summary_sakurafrp` | Through a SakuraFrp node | 经 SakuraFrp 的节点 |
| `ui.overlay.summary_openfrp` | Through an OpenFrp node | 经 OpenFrp 的节点 |
| `ui.overlay.frp_address` | Address for clients | 客户端连接地址 |
| `ui.overlay.frp_node` | Node | 节点 |
| `ui.overlay.frp_access_key` | Access key | 访问密钥 |
| `ui.overlay.frp_access_key_hint` | The access key of your SakuraFrp account. | 你的 SakuraFrp 账户的访问密钥。 |
| `ui.overlay.frp_access_key_save` | Save access key | 保存访问密钥 |
| `ui.overlay.frp_access_key_forget` | Forget access key | 忘记访问密钥 |
| `ui.overlay.openfrp_login` | Log in | 登录 |
| `ui.overlay.openfrp_logout` | Log out | 退出登录 |
| `ui.overlay.openfrp_login_waiting` | Confirm the login on the OpenFrp page. | 到 OpenFrp 的页面上确认登录。 |
| `ui.overlay.openfrp_login_open` | Open the login page again | 重新打开登录页 |
| `ui.overlay.openfrp_login_timed_out` | The login was not confirmed within 5 minutes. | 5 分钟内没有确认登录。 |
| `ui.overlay.openfrp_login_failed` | The login failed. | 登录失败。 |
| `ui.overlay.openfrp_login_expired` | The login has expired. The tunnel keeps running; log in again to pick another. | 登录已过期。隧道照常运行，要换隧道得重新登录。 |
| `ui.overlay.openfrp_openapi` | Uses the OpenFrp OPENAPI | 使用 OpenFrp OPENAPI |
| `ui.overlay.openfrp_notice` | This project is developed by its community. OpenFrp offers technical support for node problems only. | 此项目由社区开发，OpenFrp 官方不负责除节点问题以外的技术支持 |
| `ui.overlay.frp_tunnels` | Tunnels | 隧道 |
| `ui.overlay.frp_refresh` | Refresh | 刷新 |
| `ui.overlay.frp_region` | Region | 地区 |
| `ui.overlay.frp_latency` | Latency | 延迟 |
| `ui.overlay.frp_region_mainland` | Mainland China | 中国大陆 |
| `ui.overlay.frp_region_hk_mo_tw` | Hong Kong, Macao, Taiwan | 港澳台 |
| `ui.overlay.frp_region_abroad` | Outside China | 海外 |
| `ui.overlay.frp_region_outside_mainland` | Outside mainland China | 中国大陆以外 |
| `ui.overlay.frp_empty` | No TCP tunnel has local port {port}. Create one at {vendor}. | 没有本地端口为 {port} 的 TCP 隧道。到 {vendor} 建一条。 |
| `ui.overlay.openfrp_empty` | No TCP tunnel has local port {port} and auto TLS off. Create one at OpenFrp. | 没有本地端口为 {port}、关闭自动 TLS 的 TCP 隧道。到 OpenFrp 建一条。 |
| `ui.overlay.frp_console` | Open the {vendor} console | 打开 {vendor} 控制台 |
| `ui.overlay.frp_port_mismatch` | The connection port is {port}. At {vendor}, change this tunnel's local port to {port}, then apply the tunnel again. | 连接端口现在是 {port}。到 {vendor} 把这条隧道的本地端口改成 {port}，再重新应用隧道。 |
| `ui.overlay.frp_apply` | Apply tunnel | 应用隧道 |
| `ui.overlay.frp_apply_hint` | Connects through the picked tunnel and gives its address to clients and agents. | 经选中的隧道连接，并把它的地址发给客户端和被控端。 |
| `ui.overlay.frp_apply_warning` | Clients connected through {vendor} disconnect and connect again. | 经 {vendor} 连着的客户端会断开再重连。 |
| `ui.network.agent_port_frp_warning` | {vendor} has a tunnel: change its local port at {vendor} to match. | {vendor} 已选隧道：到 {vendor} 把隧道的本地端口也跟着改。 |

`ui.overlay.openfrp_notice` in Chinese is OpenFrp's own sentence, word for
word, which its terms ask for.

The state words, `state.frp_<code>`:

| `state` | English | Chinese |
| --- | --- | --- |
| `disabled` | Off | 已关闭 |
| `not_signed_in` | Not signed in | 未登录 |
| `vault_locked` | Vault locked | 保险库已锁定 |
| `no_tunnel` | Enabled, not connected | 已启用，未连接 |
| `loopback_port_taken` | Local port in use | 本机端口已有程序在用 |
| `config_failed` | Tunnel config unavailable | 取不到隧道配置 |
| `connecting` | Connecting | 连接中 |
| `connected` | Connected | 已连上 |
| `proxy_refused` | Tunnel refused by the node | 节点拒绝了隧道 |
| `port_closed` | Public port closed | 对外端口不通 |
| `login_failed` | Node login failed | 节点登录失败 |
| `unreachable` | Node unreachable | 连不上节点 |

A client's Hubs row words `reached_through` `sakurafrp` and `openfrp` as
`ui.through.sakurafrp` and `ui.through.openfrp`, **SakuraFrp** and
**OpenFrp** in both languages.

## The iOS share page's words

The iOS app's share page ([client.md](client.md), "The share page") words
its rows, its dialogs and its codes with these keys of the app's own
catalog. The password keys are the Android app's.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.forget_password` | Forget password | 忘掉密码 |
| `ui.forget_password_arm` | Press again to forget | 再按一次以忘掉 |
| `ui.remember` | Remember | 记住 |
| `ui.add` | Add | 添加 |
| `ui.upload_from_files` | Upload from Files | 从“文件”上传 |
| `ui.upload_from_photos` | Upload from Photos | 从“照片”上传 |
| `ui.more` | More | 更多 |
| `ui.rename` | Rename | 重命名 |
| `ui.save_to_files` | Save to Files | 存储到“文件” |
| `ui.delete` | Delete | 删除 |
| `ui.delete_armed` | Press again to delete | 再按一次删除 |
| `ui.retry` | Retry | 重试 |
| `ui.create` | Create | 新建 |
| `ui.name_hint` | Name | 名称 |
| `ui.empty_folder` | This folder is empty | 这个文件夹是空的 |
| `ui.share_progress` | {done} of {total} | {done} / {total} |
| `ui.share_waiting` | Waiting | 等待中 |
| `ui.job.downloading` | Downloading… | 下载中… |
| `ui.job.uploading` | Uploading… | 上传中… |
| `ui.job.renaming` | Renaming… | 重命名中… |
| `ui.job.deleting` | Deleting… | 删除中… |
| `code.share_name_taken` | This folder already holds that name. | 这个文件夹里已经有这个名字。 |
| `code.share_interrupted` | Interrupted when the app went to the background. | 应用转入后台时中断了。 |
| `code.share_photo_unavailable` | Photos did not hand over one of the picked items. | “照片”没有交出所选的其中一项。 |

**New folder**, **Open**, **Connect**, **Cancel**, the user name and password
fields and `ui.job.opening` are the desktop client's keys.

## The iOS remote desktop's words

The iOS app's **Remote desktops** page and its viewer ([client.md](client.md),
"The remote desktop viewer") use the Android app's keys for the viewer's
buttons, the Configure sheet and the codes `rdp_closed`, `rdp_core_missing`
and `rdp_login_failed`, and the desktop client's keys for the page's rows.
The bar adds one key of the app's own, which the Android app's catalog holds
too ([client.md](client.md), "The layout").

| Key | English | Chinese |
| --- | --- | --- |
| `ui.bar_desktops` | Desktops | 桌面 |

## The 0.6.0 channel and the clients' words

The codes 0.6.0 adds ([protocol.md](protocol.md), "The codes 0.6.0 adds and
removes") and the words of the clients' Apps page, Files page, Terminals
page and SSH setting ([client.md](client.md)). A code is in the hub's
`codes.json`, in each client's catalog and in each command line's
`cli/wording.py`; a `ui.*` key is in the surface that draws it.

| Key | English | Chinese |
| --- | --- | --- |
| `code.control_unavailable` | The hub is busy and did not answer; try again. | 中枢正忙，没有应答，稍后再试。 |
| `code.transport_key_missing` | The transport has not written its key yet; try again in a moment. | 传输层还没有写出密钥，稍后再试。 |
| `code.transport_apply_failed` | The transport could not be started: {detail} | 传输层没能启动：{detail} |
| `code.account_home_unknown` | The machine has not reported a home directory for {account}; set its share path. | 这台机器还没有报告 {account} 的家目录，请填写它的共享路径。 |
| `code.share_name_taken` | The machine already has a share named {name}. Give the new share another name, or rename or remove the other one. | 这台机器上已经有一个叫 {name} 的共享。请给新的共享换个名字，或者把原来那个改名或删掉。 |
| `code.samba_hosts_allow_no_loopback` | Samba's hosts allow on this machine leaves out 127.0.0.1, so the module's shares cannot answer; add it there. | 这台机器的 Samba hosts allow 没有 127.0.0.1，本模块的共享无法应答；请在那里加上它。 |
| `code.samba_interfaces_no_loopback` | Samba binds to interfaces without lo on this machine, so the module's shares cannot answer; add lo there. | 这台机器的 Samba 只绑定了不含 lo 的网卡，本模块的共享无法应答；请在那里加上 lo。 |
| `code.samba_domain_member` | Samba on this machine is a domain member, which the module's local users cannot sign in to. | 这台机器的 Samba 是域成员，本模块的本地用户无法登录。 |
| `code.share_users_unknown` | The folder shares {shares} have no account and are not served; check an account for them, or remove them. | 文件夹共享 {shares} 没有勾选任何账户，所以没有提供；请给它们勾选账户，或删掉它们。 |
| `code.share_hub_login_rejected`, a machine's share refusing the login the hub gave | The share refused the login the hub gave. Check this machine's file share in the panel. | 中枢给的登录被拒了，请在面板检查这台机器的文件共享。 |
| `code.terminal_account_missing` | No account is enabled for this machine's terminal; enable one on its machine page. | 这台机器的终端没有启用的账户，到它的机器页上启用一个。 |
| `code.account_not_enabled` | {account} is not enabled for this machine's terminal. | 这台机器的终端没有启用 {account}。 |
| `code.key_missing` | The SSH server of {account} has no key from the hub; apply the module again. | {account} 的 SSH 服务器没有中枢发的钥匙，重新应用这个模块。 |
| `code.op_unknown` | This agent cannot do {op} on files. | 这个被控端不能对文件做 {op}。 |
| `code.hub_untrusted` | The hub's key does not match; if it was reset, join it again. | 中枢的密钥对不上；中枢重置过的话就重新加入。 |
| `ui.state.untrusted`, on a hub row | Hub key mismatch | 中枢密钥不符 |
| `code.hub_key_missing` | This binding is from 0.5 and the hub no longer moves it; join the hub again with a new link. | 这份绑定来自 0.5，中枢已不再迁移；用新链接重新加入中枢。 |
| `code.port_taken` | Local port {port} is in use; give this entry another in Configure. | 本机端口 {port} 已被占用，在“配置”里给这个入口换一个。 |
| `code.client_not_running` | The client is not running; start it with nclient gui. | 客户端没有运行，先 nclient gui。 |
| `ui.panel_apps`, the page's title and its bar label | Apps | 应用 |
| `ui.app_source.module`, `ui.app_source.declared`, `ui.app_source.manual` | module, declared, manual | 模块、声明、手动 |
| `ui.app.use`, `ui.app.configure`, `ui.app.stop`, `ui.app.open` | Use, Configure, Stop, Open | 使用、配置、停止、打开 |
| `code.app_not_in_use`, **Open** on an app not in use | Use the app first. | 先点使用。 |
| `code.app_no_page`, **Open** on an app with no `http` or `https` entry | This app has no web page to open. | 这个应用没有可以打开的网页。 |
| `code.app_in_use`, **Configure** on an app in use | Stop the app first to change its local ports. | 先停止这个应用，才能改它的本机端口。 |
| `ui.app.port_dialog_title` | Local ports of {app} | {app} 的本机端口 |
| `ui.reason.terminal_no_account` | No account is enabled for this machine's terminal. | 这台机器的终端没有启用的账户。 |
| `ui.terminal.account` | Account | 账户 |
| `ui.settings.ssh_include` | SSH programs reach the machines | 让 SSH 程序直接连被控端 |
| `ui.settings.ssh_include_hint` | Whether ssh, scp, git and VS Code reach each machine as `<machine>.nt`. | 是否让 ssh、scp、git 和 VS Code 用 `<机器>.nt` 直接连到每台机器。 |
| `ui.services.apps_title`, the Services page's section | Apps | 应用 |
| `ui.services.entries`, `ui.services.add_entry`, `ui.services.entry_type`, `ui.services.entry_path`, `ui.services.entry_remove` | Entries, Add entry, Type, Path, Remove | 入口、添加入口、类型、路径、移除 |
| `ui.services.entry_share`, a `file` entry's field | Share name | 共享名 |

`ui.panel_web` and `ui.panel_ports` go with the Web and Ports pages.

## Localization

The panel, the client page and `nclient` speak English and Simplified
Chinese, `nclient` in the client's own language, its `-h` help included;
`nhub` and `nagent` stay English. Every word a surface shows comes from a catalog,
never from a literal in a component.

**One catalog format on both surfaces.** A flat JSON object per language, keys
`ui.<area>.<thing>`, `state.<token>` and `code.<code>`, values whole sentences
or labels with `{name}` placeholders. The hub keeps one file per page group
under `hub/frontend/src/locales/<language>/`; the client keeps
`client/desktop/frontend/locales/<language>.json`. `t(key, params)` reads the
current language, falls back to English, then to the key itself. A key set
differing between the two languages, a key used in the source but absent from
English, or a backend code with no `code.<code>` entry fails the tests.

**Where the language is chosen.** The hub's is a setting in
`config/web/settings.json`, asked first by `nhub setup` and by the web setup
page, changed later on the Settings page, and read before login through
`GET /api/language`. The web setup page starts in the browser's language,
Chinese for a `zh` locale and English for any other, until its language
screen sets one. The client's is a preference in its store, taken from the
system locale on the first start and changed on its own page. Nothing else
is per browser.

**The backend returns codes, not sentences.** An error a person reads is
composed in the frontend from an identifier the API returned; a backend that
returns `"port 8080 is already in use on this box"` has made itself the
translation surface, and no amount of frontend work can undo that. A
success is a code as well: an apply answers with the codes of what it did
(`xray_restarted`, `devices_pushed` with a count) and the frontend words
them, so `applied (xray restarted; desired state pushed to 1 devices)` never
reaches a Chinese page.

**A Chinese `*_invalid` code opens with 非法<名词>.** Every code whose name
ends in `_invalid` reads `非法<名词>：…` in each Chinese catalog, the noun
naming the value refused, and the rest of the sentence keeps its
placeholders and what to write instead: `volume_invalid` is `非法卷：容器
{name} 的卷 {volume} 要写成文件夹或卷名、冒号、容器里的路径。`. English
keeps its own shape.

**A translation is not a port of the structure.** Each language follows its own
typographic authority, exactly as `docs/` does: Google's developer
documentation style guide for English, 中文文案排版指北 for Chinese. Never
translate sentence by sentence — the `Whether …` shape is an English shape, and
the Chinese rendering of a switch description is whatever that guide says a
switch description is.

**What cannot be translated must not be assembled.** A string built by joining
fragments (`"port " + n + " is already in use"`) has an English word order
baked into it. Whole sentences with named placeholders survive translation;
concatenation does not.

**Interface terms keep their English beside the Chinese on first use**, the way
the Xray documentation does it, because the config keys, the upstream tools and
this standard are all English.
