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
([../coding_style/comment_style.md](../coding_style/comment_style.md)), and it
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
| the third way in | Relay | 中继 | The card, the client's hub row and the docs use it. The server it reaches is "your server" (你的服务器) in a label and VPS in the guide. |

The sidebar's lines under the two renamed entries:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.nav.overlay`, `ui.overlay.title` | Access | 外部访问 |
| `ui.nav.overlay_description` | Reaching this hub from outside | 从外面连回这台中枢 |
| `ui.nav.modules_description`, `ui.nav.modules_description_other` | Features configured on each machine | 每台机器配置的功能 |

A docs page follows this table where the term list in
[doc-author](../../doc-author/SKILL.md) offers a choice.

## Software the owner installs

Gitea, VS Code, code-server and CloudCLI are programs the machine's owner
installs on their own machine through a module. The text rules follow from
that:

| Rule | Example |
| --- | --- |
| A module page that names third-party software says that the owner installs it on that machine. | `You install VS Code Server on this machine under Microsoft's license terms.` |
| A module page names the publisher's terms only where the publisher asks for acceptance; VS Code is the one such module ([ui_behavior.md](ui_behavior.md), "Terms before a module opens"). CloudCLI's page carries no licence line. | |
| No surface says the hub downloads, provides, bundles or distributes third-party software, in either language (代为下载, 提供, 自带). A sentence about the mechanism, in a standard page or a code comment, makes the module's installer its subject. | `The module's installer fetches the archive.`, never `The hub downloads VS Code.` |
| The **About** card on the Settings page credits only the components the hub's own package carries on that system and in that edition, such as xray, CLIProxyAPI, NetBird, EasyTier and tun2socks. Gitea, VS Code, code-server and CloudCLI are never on it. | |

The VS Code notice and its button:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.vscode.terms_notice` | You install VS Code Server on this machine under Microsoft's license terms. Open them to accept them and use VS Code here. | 你在这台机器上按微软的许可条款安装 VS Code Server。打开条款即接受，之后才能在这里使用 VS Code。 |
| `ui.vscode.terms_accept` | Open and accept the terms | 打开并接受条款 |
| `ui.vscode.terms_accepted` | Terms accepted | 已接受条款 |

## The Modules page's words

The panel titles and the AI tools part of **Global configuration**
([ui_behavior.md](ui_behavior.md), "The Modules page"). The chip, the
dialog and the reason follow the desktop client's words for its AI page
where they fit, and a managed machine is a managed device, as the
**Devices** page calls it.

| Key | English | Chinese |
| --- | --- | --- |
| `ui.modules.global_title` | Global configuration | 全局配置 |
| `ui.modules.tabs_title` | Module configuration | 模块配置 |
| `ui.ai_tools.title` | AI tools | AI 工具 |
| `ui.ai_tools.use` | This machine's AI tools use the hub's AI gateway | 这台机器的 AI 工具使用中枢的 AI 网关 |
| `ui.ai_tools.accounts` | Applies to the accounts that run VS Code, code-server or CloudCLI here: {accounts} | 作用于在这台机器上运行 VS Code、code-server 或 CloudCLI 的账户：{accounts} |
| `ui.ai_tools.no_accounts` | No account runs VS Code, code-server or CloudCLI on this machine yet. | 这台机器上还没有账户运行 VS Code、code-server 或 CloudCLI。 |
| `ui.ai_tools.tool_claude`, `ui.ai_tools.tool_codex`, `ui.ai_tools.tool_gemini` | Claude Code, Codex, Gemini | Claude Code、Codex、Gemini |
| `ui.ai_tools.slot_default`, `ui.ai_tools.slot_opus`, `ui.ai_tools.slot_sonnet`, `ui.ai_tools.slot_haiku` | Default model, Opus slot, Sonnet slot, Haiku slot | 默认模型、Opus 档位、Sonnet 档位、Haiku 档位 |
| `ui.ai_tools.codex_effort` | Reasoning effort | 推理强度 |
| `state.ai_tools_switched` | Uses the hub's AI gateway | 使用中枢的 AI 网关 |
| `state.ai_tools_switched_back` | Uses its own settings | 使用自己原来的设置 |
| `code.gateway_not_serving` | The hub's AI gateway serves no model yet; set it up on the AI page first. | 中枢的 AI 网关还没有可用的模型，先到 AI 页设置好。 |

**Configure** is `ui.modules.configure`, the page's existing word. The
desktop client's reason for its disabled AI page and the code its command
line refuses with:

| Key | English | Chinese |
| --- | --- | --- |
| `ui.reason.ai_managed`, `code.ai_tools_managed` | This is a managed device: set its AI tools on the hub's panel, under Modules, Global configuration. | 这是已管理的设备，请到中枢面板的“模块”页，在“全局配置”里设置它的 AI 工具。 |

## The Services page's health words

A declared row's state word, beside the still dot the page uses for no
opinion when the row holds no health:

| Key | English | Chinese | The row |
| --- | --- | --- | --- |
| `state.checking` | checking… | 检查中… | a TCP, web or file record the hub has not probed yet |
| `state.not_checked` | not checked | 未检查 | a record the hub never probes, a UDP port; and a record whose last probe could not judge it |

A UDP port record is in neither number of the page's badge, `{healthy} of
{total} healthy`, since the hub holds no health for it.

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
| `ui.overlay.relay_title` | Relay | 中继 |
| `ui.overlay.summary_relay` | Through a server you own, over SSH | 经你自己的服务器，用 SSH 转发 |
| `ui.overlay.relay_host` | Server | 服务器 |
| `ui.overlay.relay_ssh_port` | SSH port | SSH 端口 |
| `ui.overlay.relay_account` | Account | 账户 |
| `ui.overlay.relay_key` | SSH key | SSH 密钥 |
| `ui.overlay.relay_public_port` | Public port | 对外端口 |
| `ui.overlay.relay_address` | Address for clients | 客户端连接地址 |
| `ui.overlay.relay_host_key` | Host key | 主机密钥 |
| `ui.overlay.relay_forget_host_key` | Forget host key | 忘记主机密钥 |
| `ui.overlay.relay_apply` | Apply relay | 应用中继 |
| `ui.overlay.relay_apply_hint` | Saves the relay and connects it again. | 保存中继设置并重新连接。 |
| `ui.overlay.relay_apply_warning` | Clients connected through the relay disconnect and connect again. | 经中继连着的客户端会断开再重连。 |
| `ui.overlay.relay_guide` | What to set up on your server | 服务器上要做的设置 |

The state words, `state.relay_<code>`:

| `state` | English | Chinese |
| --- | --- | --- |
| `disabled` | Off | 已关闭 |
| `not_configured` | Not configured | 未配置 |
| `vault_locked` | Vault locked | 保管库已锁定 |
| `connecting` | Connecting | 连接中 |
| `connected` | Connected | 已连上 |
| `port_closed` | Public port closed | 对外端口不通 |
| `auth_failed` | Authentication failed | 认证失败 |
| `host_key_changed` | Host key changed | 主机密钥已变 |
| `forward_refused` | Forward refused | 服务器不让对外监听 |
| `unreachable` | Server unreachable | 连不上服务器 |

## Localization

The panel and the client page speak English and Simplified Chinese; the
command lines stay English. Every word a surface shows comes from a catalog,
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
`GET /api/language`. The client's is a preference in its store, taken from the
system locale on the first start and changed on its own page. Nothing is per
browser.

**The backend returns codes, not sentences.** An error a person reads is
composed in the frontend from an identifier the API returned; a backend that
returns `"port 8080 is already in use on this box"` has made itself the
translation surface, and no amount of frontend work can undo that. A
success is a code as well: an apply answers with the codes of what it did
(`xray_restarted`, `devices_pushed` with a count) and the frontend words
them, so `applied (xray restarted; desired state pushed to 1 devices)` never
reaches a Chinese page.

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
