# Usage guide style

A usage guide gets somebody from wanting a thing to having it. It is read
through, in order, once. `misc/operations.md` is one.

It does not list fields. When the reader needs the full set, link to the
reference ([technical_guide_style.md](technical_guide_style.md)) and stop.
Rules shared with the other two kinds are in [SKILL.md](SKILL.md).

We take the [Xray-core documentation](https://xtls.github.io) as an excellent
reference for technical writing, and this page is drawn from it: the quoted
passages are theirs, and the frequencies are measured across 106 Chinese pages
and 107 English ones. The corpus and method are in [SKILL.md](SKILL.md).

## Three levels, and a guide is exactly one

Mixing two levels is what makes a guide useless to both. Xray splits theirs
into three directories and states the reader in the first line of each index.

| Level | Their name | Assumes | Gives |
| --- | --- | --- | --- |
| Beginner | 小小白白话文 / Absolute Beginner's Plain Guide | Nothing. Has not opened a terminal. | Every command, in order, one at a time. Copy and it works. |
| Standard | 入门技巧 / Beginner Skills | Has one server running — explicitly, has finished the beginner guide. | The procedure, and the mechanism behind each step. |
| Advanced | 进阶技巧 / Advanced Skills | Knows the system and the network stack. | An approach and its trade-offs. Skips the obvious. |

Their own statements of level, which are the model to copy:

> 这个章节是【从零开始】的基础课，新来的同学好好看好好学哦

> 这个章节是入门级的 Xray 使用心得分享，主要分享一些 Xray 常用功能模块的**原理说明**

> 如果您已经熟悉 Xray, 那么这里的经验可以让您更加发挥 Xray 的威力

## State who the guide is *not* for

Both halves, one sentence each, in the opening. A reader who leaves at line
three because it was not for them has been served well.

The beginner guide gives this its own numbered section — 「1.2 这篇文档不是写给谁的？」:

> 包括但不限于：各路大神大能、懒得自己折腾的小白…总之只要有技术基础、或不愿不想自建的同学，您直接关闭本文即可

and then warns about its own length in advance, which is a contract with the
reader rather than an apology:

> 啰嗦声明：基于本文【零基础用户】的目标受众，许多内容会尽力详尽说明，所以语言偏啰嗦，请做好心理准备。

```text
# GOOD — English equivalent
This is the ground-up guide: it assumes you have never opened a terminal, and
every command is written out. If you already run a server of your own, read
misc/operations.md instead — this one will feel slow.
```

## Sentence length does not change; the person does

The most counter-intuitive measurement in the whole study, and the one most
worth acting on:

| Layer | Chinese chars/sentence | 你/您 | 我们 | 我 |
| --- | --- | --- | --- | --- |
| Reference | 39.1 | 2.0% | 0.1% | 0.3% |
| Beginner | **39.6** | **19.7%** | 5.4% | 5.8% |
| Standard | 42.5 | 10.5% | 8.0% | 4.5% |
| Advanced | 41.1 | 5.5% | 2.4% | 0.6% |

| Layer | English words/sentence | you | we | I | passive |
| --- | --- | --- | --- | --- | --- |
| Reference | 12.4 | 6.1% | 0.1% | 0.1% | 16.8% |
| Beginner | **13.8** | **27.3%** | 5.2% | 5.9% | 6.5% |
| Standard | 14.7 | 13.9% | 9.0% | 5.3% | 12.8% |
| Advanced | 14.1 | 11.6% | 3.7% | 1.2% | 13.8% |

Beginner sentences are the **same length** as reference sentences — 39.6 against
39.1 characters, 13.8 against 12.4 words. What moves is the person: 你/您 goes
from 2.0% to 19.7%, a factor of ten.

Do not write shorter sentences for less experienced readers; they are already
as short as they should be. Talk to the reader instead. Writing down to
somebody shows up as chopped sentences and repeated reassurance, never as
clarity.

## One command per block, at the beginner level

Beginner shell blocks in the corpus have a median of **one line**. They do not
write "paste these six commands" — `wget …`, `sudo bash …`,
`rm ~/install-release.sh` each get their own block under a numbered step.

Six commands in one block is a wall to a reader who cannot tell which one
failed.

Standard and advanced guides may give a block that runs as a unit, with a
comment on each line that makes a decision. Ours, from `misc/operations.md`:

```bash
# 1. Did DHCP work? Expect 192.168.100.x with .1 as gateway and DNS.
ip addr show; ip route

# 2. Does the proxy path work? Expect a node's address, not your ISP's.
curl -s https://ifconfig.me; echo
```

Every step says what a correct result looks like. A reader who cannot tell
success from failure cannot follow a guide.

## Configurations are complete and runnable

The opposite of the reference rule. Guide JSON in the corpus runs 15–20 lines
against the reference's 12, because here it gets pasted and has to work.

Comment only the lines the reader must change. Comments mark decisions, never
syntax:

```json
"port": 10086, // 服务器监听端口
"id": "b831381d-…" // 记得替换这个字段，使用 `xray uuid` 或 `uuidgen` 生成
"ip": ["geoip:private", "geoip:cn"], // 绕过局域网和国内IP段
```

Then close the block with one sentence naming what changed:

> 上述配置唯一要更改的地方是你的服务器 IP 和用户 uuid，配置中已注明。

Ours:

```json
{
  "host": "192.168.100.1",
  "port": 8317,
  "api_key": "PLACEHOLDER_CLIENT_KEY"
}
```

Only `api_key` changes — copy it from the Credentials page. Everything else is
the same on every machine.

A value the reader must replace is written so it cannot be mistaken for a real
one: `PLACEHOLDER_CLIENT_KEY`, never a plausible-looking string. The secret
scan reads documentation too.

## Translate the configuration into a sentence

After a block that is not self-evident, restate it in one plain sentence, and
mark the register shift explicitly so the reader knows what just happened:

> 这一段配置用人话要怎么解释呢？
>
> 1. **`Xray` 的入站端口 `[inbound port]` 是 `443`**
>    即由 `Xray` 负责监听 `443` 端口的 `HTTPS` 流量

> 下面的入站配置示例，用大白话说就是：数据按照 `socks` 协议，通过 `10808` 端口，从本机 `127.0.0.1` 流入 `Xray`。

In English the marker is "in plain terms" or "read out loud, this says". In
Chinese it is 「用大白话说就是」 or 「用人话解释」.

Note the term pairing — 「入站端口 `[inbound port]`」. A Chinese guide gives the
English term on first use, because the interface and the config keys are
English. An English guide has no reason to do the reverse.

## Diagrams belong here, not in the reference

All 12 mermaid diagrams in the corpus sit in the standard-level guides. A
diagram explains a mechanism; the reference lists fields.

## Structure of a beginner chapter

Numbered sections throughout (`## 7.4`, not `## Configuring the server`), so a
reader can say exactly where they are stuck. Their chapters close with a
progress bar:

```text
## 7.x 你的进度
> ⬛⬛⬛⬜⬜⬜⬜⬜ 37.5%
```

We do not need the bar, but we need what it is for: a beginner guide says how
far along the reader is and what comes next.

## Hand off instead of half-teaching

When the next thing is beyond this guide's level, the whole section is one
sentence and a link. Their entire section 7.9:

> ## 7.9 服务器优化之三：更丰富的回落
>
> 如果你需要更丰富的回落功能，可以参考 [《回落 (fallbacks) 功能简析》](https://xtls.github.io/document/level-1/fallbacks-lv1.html)

That one sentence is the boundary between two levels. In the beginner chapter
`fallbacks` appears only as a line in a copyable config with a
`// 默认回落到防探测的代理` comment — **no explanation at all**, because a beginner
needs it to work, not to understand it. Understanding is the next level up.

```text
# GOOD — the entire section
## Splitting the LAN into VLANs

One port per VLAN, with an untagged main: misc/operations.md.
```

## End by signing off, not summarising

At most one sentence, saying the thing is done, never what the thing was:

> 至此，`Xray` 的【回落】功能就介绍完了。希望本文能够对你理解 `Xray` 的强大有所帮助。

```text
# BAD
To summarise, we have configured the LAN interface, set the DHCP range,
enabled the proxy, and verified that traffic flows through the exit node...

# GOOD
That is the whole path: a device on the LAN port now reaches the internet
through your own nodes.
```

## Sentence templates

| Situation | Chinese | English |
| --- | --- | --- |
| Register shift | `这一段配置用人话要怎么解释呢？` / `用大白话说就是：…` | `In plain terms: …` |
| Term pairing | 入站端口 `[inbound port]` | — (English needs only one) |
| Level statement | `这个章节是【从零开始】的基础课` | `This is the ground-up guide.` |
| Not for you | `只要有技术基础的同学，您直接关闭本文即可` | `If you already …, read <other> instead.` |
| Hand-off | 如果你需要\<更多\>，可以参考《\<标题\>》加链接 | For \<more\>, see \<title\> as a link. |
| Sign-off | `至此，<X> 就介绍完了。` | `That is the whole path.` |
| Step check | `# N. <目的>。应该看到<正确结果>。` | `# N. <purpose>. Expect <correct result>.` |
