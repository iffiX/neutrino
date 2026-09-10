# Documentation style

Three kinds of document live in this repository, each written differently:

- [technical_guide_style.md](technical_guide_style.md) — reference. What a
  field is, what it accepts, what it defaults to. `misc/config.md` is one.
- [usage_guide_style.md](usage_guide_style.md) — how to do a thing, for a
  stated level of reader. `misc/operations.md` is one.
- [development_guide_style.md](development_guide_style.md) — how to change the
  code. `AGENTS.md` and the rest of `skills/core-code-author/` are these.

This page holds what all three obey, and how the two languages differ.

We take the [Xray-core documentation](https://xtls.github.io) as an excellent
reference for technical writing — it stays readable at length without turning
into filler, in two languages — and these four pages are drawn from a full-text
study of it: 106 Chinese pages (424,424 characters) and 107 English pages
(95,800 words).

The evidence is therefore measured, not asserted. Every count in these pages
comes from that corpus, and quoted passages keep their original language.

## The boundary between the three is hard

A reference page says what a thing is. A guide says how to do something with
it. Neither writes the other's half; they link and stop.

Xray does this strictly enough to be worth copying. `config/features/fallback.md`
documents every field of the feature, then ends:

> - 您可以查看更多的关于 Fallbacks 的使用技巧和心得
>   - [Fallbacks 功能简析](https://xtls.github.io/document/level-1/fallbacks-lv1.html)

It refuses to teach on a reference page. The traffic runs both ways —
`config/routing.md` opens by handing the explanation away:

> 有关路由功能更详细的解析：[路由 (routing) 功能简析](https://xtls.github.io/document/level-1/routing-lv1-part1.html)。

One word, `fallbacks`, appears at four depths across their site with **zero
overlap**: a bare `// 默认回落到防探测的代理` comment in the beginner chapter, a
seven-section explanation in the level-1 guide, a field table in the reference,
and a one-line cross-reference in the protocol page. Nobody repeats anybody.

"Briefly mentioning" the other half is how both pages rot: the copy drifts, and
neither is authoritative afterwards.

```text
# BAD — a field reference that starts teaching
`is_geoip_split_enabled`: bool

Whether to route Chinese destinations directly. Most people want this on,
because otherwise domestic sites go through an overseas node and get slower.
To set it up, open the Proxy page, turn on the switch, click Apply, and wait
about two seconds for xray to restart...

# GOOD — the field, then a link
`is_geoip_split_enabled`: bool

Whether `geosite:cn` and `geoip:cn` destinations bypass the proxy. Default
`true`; `false` sends every destination through the balancer.

Setting it up: [misc/operations.md](../misc/operations.md).
```

## Rules every document obeys

### Open with a definition or a conclusion

Never a preamble. `X is …` / `X does …`, then stop. The title is the thing's
own name, unadorned.

Real openings, complete, nothing trimmed:

| Page | Whole first paragraph |
| --- | --- |
| `# HTTP` | 「HTTP 协议。」 (5 characters) |
| `# mKCP` | 「mKCP 使用 UDP 来模拟 TCP 连接。」 |
| `# Sockopt` | 「Sockopt 用于配置底层网络行为。」 |
| `# TLS` | 「TLS 是常见的传输层加密方式。」 |
| `# REALITY` | 「REALITY 是对 TLS 的一种修改，通过借用目标站点的 TLS 外观与握手特征来完成伪装。」 |

A page about something already familiar may be one sentence long. "HTTP 协议。"
is a legitimate complete opening — they did not explain HTTP, and neither
should we explain JSON, systemd, or git.

### Never write a summary section

Across their 64 reference pages: **zero** summary sections. The last heading is
always the last object being defined. In 424,424 characters of Chinese there is
exactly **one** `## 小结`, in a community-contributed page.

A guide may sign off in one sentence. That is an acknowledgement, not a
summary — it says the thing is finished, never what the thing was:

> 至此，`Xray` 的【回落】功能就介绍完了。希望本文能够对你理解 `Xray` 的强大有所帮助。

### A document says what exists

Documentation is a description of the current thing, never a record of what
the thing used to be. A removed command, a renamed field, an approach that was
tried and dropped — none of it appears anywhere: not in a changelog line, not
in a "what moved" section, not in a parenthesis beside its replacement. The
reader is told what to type today.

This is the one rule here that is not drawn from the corpus. It is this
project's, because a repository that documents its own deletions accumulates a
second history that drifts from git and outlives the reason it was written.

```text
# BAD — the page carries its own past
### apply

Renders every config and applies it. (This was `render` before 0.2.)

## What moved out

`nhub scan-secrets` no longer ships; it is a development command.

# GOOD — the page carries the present
### apply

Renders every module's config from `config/` and makes it true on the box.
```

A deprecation the user asked for is not a deletion. A feature kept working
while its callers move off it still exists, so it is documented like anything
else, with the thing that replaces it named.

### Transition filler does not appear

These are measured zeroes across the whole corpus, not "used sparingly":

| Chinese (424k chars) | Count | English (96k words) | Count |
| --- | --- | --- | --- |
| 值得注意的是 | **0** | It should be noted | **0** |
| 需要强调的是 | **0** | In conclusion | **0** |
| 综上所述 | **0** | To summarize | **0** |
| 总而言之 | **0** | In summary | **0** |
| 总的来说 | **0** | Furthermore | **0** |
| 在当今 | **0** | In today's | **0** |
| 随着…的发展 | **0** | As we all know | **0** |
| 首先…其次…最后 (as scaffolding) | **0** | In this section | **0** |
| 深入探讨 | **0** | leverage (as a verb) | **0** |
| 本文将 | **0** | Let us | **0** |

The control group, from the same corpus: 用于 192, 当…时 153, 建议 71,
默认值为/默认为 101, 可选 53; `such as` 137, `Default` 79, `recommended` 66,
`For example` 50.

**Information words run in the hundreds. Filler runs at zero.** That gap is the
whole style.

### A self-evident list item gets no gloss

Their entire `config/features.md` page body:

> Xray 具备以下特性：
>
> - [XTLS 深度剖析](https://xtls.github.io/config/features/xtls.html)
> - [Fallback 回落](https://xtls.github.io/config/features/fallback.html)
> - [Browser Dialer](https://xtls.github.io/config/features/browser_dialer.html)
> - [多文件配置](https://xtls.github.io/config/features/multiple.html)
> - [反向代理 / 内网穿透](https://xtls.github.io/document/level-2/vless_reverse.html)

Five links, zero descriptions. The urge to write a sentence under each was
suppressed, because the titles already carry it.

Their level-2 index **does** gloss every entry — those titles are long
community-contributed ones that are not self-explanatory. Gloss when the name
does not carry it, not by default.

### Say what is not true

The strongest single move against an AI-flavoured document. Xray puts this at
the top of `/document/`:

> ::: tip
> 这个部分有相当久没有更新了，有的地方可能不是很靠谱，我们只会尽量保持配置文件的文档更新，如果有地方踩坑了有修改建议欢迎 PR 修正。
> :::

and at the top of `/config.md`:

> ::: warning 版本说明
> 本文档与最新 release 同步；而一键脚本大多安装 GitHub 标记为 `Latest` 的版本，它有时不是最新 release，因此部分字段可能无效或行为与文档描述不一致。
> :::

They also argue against their own features. From the Mux documentation:

> Mux 是为了减少 TCP 的握手延迟而设计，而非提高连接的吞吐量。使用 Mux 看视频、下载或者测速通常都有反效果。

and from the REALITY page:

> 回落限速是一种特征，不建议启用，如果您是面板/一键脚本开发者，务必让这些参数随机化。

Telling somebody not to turn on the feature you are documenting is a thing no
generated text does. Where a page is stale, where a feature should not be used,
who a guide is not for — one sentence each, up front.

### Do not bury the misuse

Put what the reader is most likely to get wrong in the first half of the
paragraph, not in a closing caution. The Mux paragraph puts its two most
valuable sentences third and fourth of five, not last.

## Warnings come in three levels

Ordinary risk is prose, in place. Only these three get pulled into a box, and
they keep their weight by being rare. Their measured ratio across the whole
site is **tip 118 : warning 50 : danger 23**, roughly 5 : 2 : 1. Two thirds
carry no custom title.

| Level | For | Shape |
| --- | --- | --- |
| tip | An easier way, an equivalent form, a common case | One or two sentences, level tone |
| warning | A real consequence the reader can hit | One paragraph of mechanism, one of remedy |
| danger | Breaks the configuration; a hard uniqueness or ordering constraint | Two lines at most |

**danger** — short, and bold falls on the single decisive word:

> 当其不为空时，其值必须在所有 `tag` 中**唯一**。

> 当多个属性同时指定时，这些属性需要**同时**满足，才可以使当前规则生效。

**warning** — mechanism first, then named ways out. No "please be careful":

> 为了伪装的效果考虑，Xray 对于鉴权失败（非合法 REALITY 请求）的流量，会**直接转发**至 target.
> 如果 target 网站的 IP 地址特殊（如使用了 CloudFlare CDN 的网站） 则相当于你的服务器充当了 CloudFlare 的端口转发，可能造成被扫描后偷跑流量的情况。
>
> 为了杜绝这种情况，可以考虑前置 Nginx 等方法过滤掉不符合要求的 SNI。
> 或者也可以考虑配置 `limitFallbackUpload` 和 `limitFallbackDownload`，限制其速率。

**tip** — flat, often a single equivalence:

> `"ext:geoip.dat:cn"` 等价于 `"geoip:cn"`

The tone across all three is: state the consequence, do not perform alarm.
Measured, they write 会导致/可能导致 52 times and 建议 71 times, against
请勿/不要/切勿 42 — consequences outnumber prohibitions.

A fourth kind of caution never gets a box. It is a plain paragraph opening with
`注意，` (27 occurrences), and it is the most imitable sentence on their site:

> 注意，监听一个端口是相当昂贵的操作，监听端口范围太大可能造成占用显著提高甚至导致 Xray 无法正常工作，一般来说监听数量接近四位数时可能就会开始出现问题，要使用一个很大的范围请考虑使用 iptables 进行重定向而不是在这里设置。

One sentence carrying **cost, consequence, a quantified threshold ("四位数"),
and an alternative**. Expanding that into four sentences and a callout box adds
nothing.

```text
# BAD — alarm with no exit
WARNING: Be very careful when changing the LAN subnet! This is a dangerous
operation that could have serious consequences for your network!

# GOOD — what happens, then what to do
Changing the LAN subnet invalidates every device's DHCP lease and every SSH
host key pinned to an old address.

Renew leases with `sudo systemctl restart neutrino_router`, and remove and
re-add any device whose SSH details were stored.
```

## English and Chinese

Code is English only — comments, docstrings, commit messages
([../coding_style/comment_style.md](../coding_style/comment_style.md)).
Documentation is not: a page may exist in both languages, and user-facing
guides are the most likely to need it.

Each language follows its own typographic authority rather than a translation
of the other's rules. Xray binds them explicitly, and it is why neither version
reads like a translation:

| | Authority | Formatter |
| --- | --- | --- |
| English | [Google developer documentation style guide](https://developers.google.com/style) | prettier |
| Chinese | [中文文案排版指北](https://github.com/sparanoid/chinese-copywriting-guidelines) | prettier |

Their contributing guide says plainly: 「注：存在格式问题的 PR，将有可能被拒绝。」
Style is enforced, not left to goodwill.

### What differs between the two

**Sentence length is not a translation constant.** Chinese averages 35–42
characters per sentence; English averages 12–15 words. A 40-character Chinese
sentence becoming a 40-word English one means the English is padded.

**Chinese needs the spacing rules.** From 排版指北, and worth stating because
they are the errors that appear most: a space between Latin and CJK characters
(`Xray 使用 UDP`), full-width punctuation in Chinese text（，。：；「」）,
half-width for numbers and Latin, and no space between a number and a
full-width unit.

**Term pairing runs one way.** A Chinese page gives the English term beside the
Chinese on first use, because the interface, the config keys and the upstream
documentation are all English:

> **`Xray` 的入站端口 `[inbound port]` 是 `443`**

An English page does not do the reverse. It has no reason to.

**A translation is not a port of the structure.** Same sections, same field
order, same examples — but each written in its own language's register. Never
translate sentence by sentence: that is exactly what produces text that is
grammatical and unreadable.

### Where they got it wrong

Two mistakes from the same corpus, so we avoid them:

- The English site names one section two ways: navigation says
  `Absolute Beginner's Plain Guide`, the page body says `Project X for Dummies`;
  `Beginner Skills` vs `Beginner Tips`. **A section has one name in every
  language, used everywhere.**
- Auto-numbered callout titles — `::: tip TIP 1`, `TIP 2`, `TIP 3` — carry no
  information. Give a callout a real title or none.

## A little personality is allowed

Not much, and never in a reference page. In guides and development notes, a
line with a voice is more memorable than a neutral one and costs nothing:

> 如果你不幸使用 Windows, 请 **务必** 使用 Powershell

> 如果你闲的没事干，可以试试 GitHub 官方工具: `gh repo clone XTLS/Xray-core`

Both say the whole thing and stop. The test is whether the sentence would
survive being cut to its content — if the joke is the content, keep it; if it
is wrapping, drop it.
