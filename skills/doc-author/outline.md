# The site's outline and the shape of each page

An outline is what a site or a page holds, in order, before any prose exists. This
file holds the user guide's outline, the shape of the overview pages, and the shape
of every kind of page written in this repository: who reads it, how it opens, what
it holds, what it refuses, and the checks a reviewer runs beyond `checklist.md`. How
a finished page looks on screen is in `layout.md`.

## Outline and finished page

| Stage | Holds | Reason |
| --- | --- | --- |
| Outline of a page | At most 10 very short lines that say what the page does. | The user reads outlines fast, and a long outline tires the reader before any prose exists. |
| Finished manual page | As much as a reader who knows nothing needs to finish the job alone: where to go, what to press, what to fill in, what appears next, how success looks and what to do when it fails. Its first sentence starts with the thing the title names and says what it is, or speaks to the reader as `你`. It is never a slogan, a question or a list of topics. | The outline's brevity does not carry over, and a page's first sentence is the first thing a technical reader judges it by. |

A finished page is connected prose. A list holds real steps or truly parallel items,
and an item is a whole sentence. Every step of installing and of using something has
a picture, placed as `layout.md` says.

## The user guide's outline

The sidebar has these groups, in this order. A group with `+` is folded under its
first page. The address of a page stays the same when its place in the sidebar
moves, because READMEs and posts link to it.

| Group | Page | Address |
| --- | --- | --- |
| 概览 | 微子·中枢是什么 + | `/overview` |
| | 工作原理 | `/how_it_works` |
| | 安全模型 | `/share/security` |
| | 数据和外连 | `/hub/what_it_holds` |
| | 和别的工具比 | `/compare` |
| | 常见问题 | `/faq` |
| | 快速上手 | `/quick-start` |
| 中枢 | 安装中枢、总览、网络形态、代理、AI 网关、被控端、客户端、设置、从 0.5 升级、卸载 | `/hub/...` |
| 一键部署 | 在一个系统上安装应用、应用的分类，然后按用途分组的应用页：系统访问、写代码、AI 工作流、论文和笔记、自己的服务 | `/deploy/...` |
| 到处使用 | 安装客户端、加入中枢、桌面客户端、Android、iOS，从外面连回来（选一种，下面是每一种），客户端高级功能 | `/access/...` |
| 任意分享 | 分享一个应用 | `/share/web_share` |
| 参考 | nhub、nagent、nclient、支持的平台、故障排查、面板菜单对照表、术语表 | `/reference/...` |

The guide has one set of pages and pictures, for the international edition. The China edition gets no page, picture or section of its own. Its differences appear in three places alone: one short sentence on the hub's install page, the proxy page's statement that the edition lacks the feature, and the network page's table of modes. Its download commands stay in the install tabs.

## The overview pages

Reader: someone who saw the short front page, has an impression of the product, and
now wants to know what it really is before installing. The front page refuses
mechanism; these pages hold it, named exactly.

| Page | Holds, in order | Refuses |
| --- | --- | --- |
| 微子·中枢是什么 | The definition. A short version that names the mechanism. One picture of the panel and the phone. Why the product exists. The core concepts, each in one or two sentences. What the product does and what the reader remains responsible for. A table from the reader's situation to the next page. | Steps. A row of unconnected claims. |
| 工作原理 | The three parts and what each does. What runs where. How a device reaches the hub, and each way in. How an app is reached through the hub. The technology by name. What happens when a part stops. | Steps. Design history. |
| 安全模型 | `快速回答`: plain answers in one table, then what they rest on and what is not protected. `技术架构`, for technical readers: the connection topology with the browser as a special client, how the port picks a path, the member handshake, anti-scanning, anti-DoS, how data is relayed, the protocol compared with the last one with measurements. Each with a diagram where a mechanism needs one. | Claims stated as an absence that the reader cannot test. Colloquial wording outside `快速回答`. A protection threshold or timing the reader can do without. |
| 数据和外连 | What the hub stores and where. Every outbound connection, with its host and the feature that makes it, and which ones stop when that feature is off. | Anything the hub does not do. |
| 和别的工具比 | Products the reader knows, one table. On the network side Tailscale alone, never frp, EasyTier or NetBird. | Prices without their reading date. |
| 常见问题 | The questions readers asked, grouped, each answered in two or three sentences with a link. | Questions nobody asked. |

### Sentence shapes for an introduction

These shapes come from how comparable products introduce themselves inside their
docs. Each is used once, in words written for this product.

| Shape | Where it was seen | What it does |
| --- | --- | --- |
| A definition naming the category and where it runs | Coolify: "an open source, self-hostable platform for deploying and managing applications... on servers you control" | The reader places the product at once. |
| A short version that names the mechanism | Coolify: "connects to each server over SSH, prepares the server to run Docker workloads, and coordinates builds" | The reader learns what actually happens. |
| Components named, each with its job | NetBird: "four components"; Beszel: hub and agent | Later pages can use the names. |
| Technology named | NetBird: WireGuard, Pion ICE, Coturn | A technical reader can judge the design. |
| What the product does and what stays with the reader | Coolify: "Coolify coordinates", "You remain responsible for" | The reader knows who answers for what. |
| A sentence saying which page to read first | Pangolin: "Read it first." | The reader stops wondering about order. |

## Landing README

Reader: someone on GitHub deciding in one screen whether to install. `README.md`
is Chinese, the default; `README.en.md` is English. The two come from one outline.
Opens with the product's name and what the reader gets, in one line.

| Part | Holds | Budget |
| --- | --- | --- |
| Top | the icon, the name as the only H1, the site's address, one line on what the reader gets, the badges, links to the demo and to the site's install and docs, a picture of the product | one screen |
| What it is | the definition first, then what each part does and where it runs, then the reader's trouble it removes, one picture | one sentence, two lines, one sentence |
| Blocks | one per thing the reader gets: a heading, the text, one picture | three blocks, three lines of text each |
| Comparison | one line per claim, then a table against products the reader knows; on the network side Tailscale alone, never frp, EasyTier or NetBird; the full table on the site | ten rows |
| Install | the simplest case: one computer, one package, the phone app, one scan; the other ways folded | three steps |
| FAQ | the questions readers asked, by category and fact, folded | four questions, two lines each |
| Docs and community | the docs, the forums, a request for help | one list |
| Apps | the software the product deploys and does not ship: its project link, one line, the page on deploying it | one table |
| Acknowledgements | the software the product ships | one list |
| Licence | the licences | two lines |

Refuses: feature-by-feature detail (the guide has it), uninstall steps and
security mechanism (the site has them), design rationale (the design pages have
it), the three-package model before the end of the install, roadmap or history,
slogans in headings.
Checks: every claim shows in a picture or holds in the product as shipped; the
install block runs as pasted; the two READMEs' headings map one to one.

## Site home page

Reader: someone who has not installed and knows no term of the product, deciding
from one screen and a short scroll. Opens with what the reader gets, in one
line, beside the product on screen.

| Part | Holds | Budget |
| --- | --- | --- |
| First screen | the name, one line on what the reader gets, one smaller line on systems and licence, two buttons, the mascot, a product screenshot | one screen |
| Blocks | a heading naming what the reader gets, the text, one picture | seven blocks, three lines of text each |
| Comparison | products the reader already knows; on the network side Tailscale alone, never frp, EasyTier or NetBird, which are ways in the product uses | three lines |
| Start | the simplest case: one computer, one package, the phone app, one scan | three steps |

The page states an absence where the reader can check it (nothing to install, no
server to buy), and 同学 names the person a link goes to. The rest of `SKILL.md`
holds.

Refuses: port numbers, protocols, timings and other mechanism (the overview pages
have them), internal names such as the agent, the three-package model, a line
that holds only in a case the page does not name, a recap.
Checks: a first-year student with no background can say what the product gives;
every claim shows in a picture or holds in the product as shipped; security
takes one common term and one line.

## App page

Reader: a user who runs the product and wants one app on one system, and knows
nothing else. A composite: a how-to with small reference tables. Opens with what the
app is and who it suits.

| Section | Holds |
| --- | --- |
| The opening | what it is, in the page's first sentence and one short paragraph, then the facts strip from `layout.md` |
| 支持的系统 | one table: the system, the architectures, and the Neutrino Hub version that first supports it, read per system from the release tags |
| 安装 | every step on the panel, each with its picture, so the reader never has to leave the page; steps every app shares are written out, and a link is for detail only |
| 使用 | every step on a client, each with its picture, then the app's own first run |
| 分享 | whether it can be shared and how, the account a visitor uses, the dialog's warning |
| 注意 | what someone inside it can do |
| 设置 | one table of the app's own settings, starting with which of them can stay at their defaults |
| 卸载 | the steps and whether its data stays |

Steps shared between app pages read the same on each page, because a reader reads
one page. Everything that belongs to this app is written for this app.

Refuses: other apps, design reasons.
Checks: the facts strip matches the manifest's platforms; the share section
matches its `web_share`; the uninstall section matches its `uninstall_data`; each
step of 安装 and 使用 has its picture.

## Quick start (tutorial)

Reader: a first-time user with a fresh box who wants a working hub in one
sitting. Opens by naming what is running at the end and how long it takes.

Shape: prerequisites as a list; then one procedure per stage, each ending in
something the reader can see; the last step shows the panel in the state the
opening promised. Every step has its picture.

Refuses: alternatives, options, flags the path does not need, explanation of
why, links out mid-procedure. Every step on the path works on a fresh box.
Checks: a fresh reader following only the page reaches the promised state;
no step has a choice in it; each stage ends in a visible result.

## How-to guide

Reader: a user who has one goal and knows nothing else about the product. Opens
with what the page is or with the first step, then the prerequisites; it does not
open with the state the reader has at the end.

Shape: a title naming the goal ("Route one device through the tunnel"); one
procedure, or a few under H3s in the order the reader performs them; options
inside a step only when the goal forks; a term the reader meets first is explained
in one clause; a reference table linked or, when short, placed after the procedure.
Every step has its picture.

Refuses: explaining design, a recap.
Checks: each H3 is a step group; a fork is stated as a condition before its
instruction; a reader who knows nothing reaches the goal from the page alone.

## Reference (CLI reference, option tables)

Reader: a user mid-task looking up one entry. Opens with a sentence naming the
program or the table's subject; the entries follow.

Shape mirrors the product: one section per program, one row per subcommand or
option, in the order the program lists them. Each row: name, what it does in
present tense, its arguments, its exit codes or refusal codes.

Refuses: procedures, why, opinion, examples longer than one command line.
Checks: the structure matches `--help` output; every row uses the same column
set; every code the program returns has a row; no sentence addresses "you".

## Troubleshooting

Reader: a user with a symptom on screen. Opens with one line on how to read the
page; entries follow, one per symptom.

Each entry has a fixed shape: the symptom as the reader sees it (the code in
inline code, the label in bold), the cause in one sentence, the fix as a
procedure. Entries are grouped by the surface the symptom appears on.

Refuses: explaining the mechanism beyond the cause sentence, listing symptoms
nobody has reported, an English sentence in place of the code.
Checks: each entry's symptom is greppable from the interface; each fix ends in
a check that the symptom is gone; the same code appears in only one entry.

## Design page (explanation)

Reader: an agent about to change code. Opens with a definition of the concept the
page is about.

Shape: the concept, the rule or the mechanism, the reason, the consequences, in
that order; a table where the content enumerates; each rule is a checkable
sentence with its reason in the same row.

Refuses: procedures, exhaustive option lists.
Checks: a reader can say afterwards why the thing is this way; every rule traces
to a consequence stated on the page; nothing describes a planned state.

## State notes (`tmp-docs/memory.md`)

Reader: the next agent, with no conversation history. Opens with the state of
the product as of the note: versions, what ships, what is open.

Shape: reference in form. One section per area; each line a present-tense fact
or an open item with who decides it. Superseded facts are removed, never
struck through or dated as history.

Refuses: narrative of how the state was reached, opinions, plans without an
owner, anything already in a design page (link to it instead).
Checks: every line still true today; no line duplicates a design page; a
fresh agent can act on each open item without asking what it means.
