# Technical guide style

A technical guide answers "what is this field, and what may I put in it". It
is looked things up in, not read through. `misc/config.md` is one; so is any
API reference we add.

It does not teach. The moment a page starts explaining why somebody would want
a setting, that is a usage guide ([usage_guide_style.md](usage_guide_style.md));
link and stop. Rules shared with the other two kinds — open with a definition,
no summary section, no filler — are in [README.md](README.md).

We take the [Xray-core documentation](https://xtls.github.io) as an excellent
reference for technical writing, and this page is drawn from it: the quoted
passages are theirs, and the frequencies are measured across 106 Chinese pages
and 107 English ones. The corpus and method are in [README.md](README.md).

## Page shape

Every reference page is the same shape, and the sameness is the point: by the
second page a reader stops reading structure and only reads content.

```text
# <name>                          ← the thing's own name, nothing appended
<one-sentence definition>.
<optional: one or two sentences of constraint or cost>
[optional ::: tip]

## <XxxObject>
`XxxObject` is <where it lives in the file>.     ← fixed anchor sentence

```json
{ ...the whole object, every field present... }
```

> `field`: type
<description>

> `field2`: type
<description>

### <NestedObject>                ← same structure, recursively
```

The page ends when the last field ends. No closing section.

## Anchor every object to where it is really seen

One fixed-format line per documented object, worded identically every time, so
a reader recognises it without reading it. Xray uses
「`XxxObject` 对应配置文件中 `xxx` 项」 on all 64 reference pages. Ours:

```text
`RouterNetworkConfig` is the whole of `config/router/network.json`.
`NodeObject` is one element of the `nodes` array in `config/xray/nodes.json`.
`GET /api/nodes` returns `NodeListView`.
```

## Field entries follow one order

There are 465 field definitions in the corpus and they follow one sequence.
Every field, every time — stopping as soon as a step has nothing to say. Most
fields need three lines.

1. **The type line** — `` > `name`: type ``
2. **Required or optional as the literal first word** — `Required, …` /
   `Optional, …`
3. **One sentence of meaning**
4. **The default, and what that default does**
5. **Each accepted form, one per line, with an example**
6. **Constraints, cost, and the way out** — its own paragraph

The short form, which most fields use — three lines and done:

> `privateKey` : string
>
> 必填，执行 `./xray x25519` 生成。

The long form, showing all six steps. This is the single best field entry on
their site:

> `port`: number | "env:variable" | string
>
> 端口。接受的格式如下:
>
> - 整型数值：实际的端口号。
> - 环境变量：以 `"env:"` 开头，后面是一个环境变量的名称，如 `"env:PORT"`。Xray 会以字符串形式解析这个环境变量。
> - 字符串：可以是一个数值类型的字符串，如 `"1234"`；或者一个数值范围，如 `"5-10"` 表示端口 5 到端口 10，这 6 个端口。
>
> 当只有一个端口时，Xray 会在此端口监听入站连接。当指定了一个端口范围时，范围内的端口都会由 Xray 监听。
>
> 注意，监听一个端口是相当昂贵的操作，监听端口范围太大可能造成占用显著提高甚至导致 Xray 无法正常工作，一般来说监听数量接近四位数时可能就会开始出现问题，要使用一个很大的范围请考虑使用 iptables 进行重定向而不是在这里设置。

Note 「这 6 个端口」: given a range, they state its size, so nobody has to work
out whether the endpoints are included. Do that.

In English the same entry reads:

```text
`port`: number | "env:variable" | string

Required, the port to listen on. Accepts:

- a number — the port itself, `1080`
- an environment variable — `"env:PORT"`, read as a string
- a string — a number, `"1234"`, or a range, `"5-10"`, meaning ports 5 to 10,
  six ports in all

A single port is listened on; a range listens on every port in it.

Listening on a port is expensive. A range approaching four figures is enough
to degrade the service; redirect with nftables instead of widening the range.
```

## Types are written as values

The type line **is** the table of allowed values. Never
`string (see below for allowed values)`.

Measured distribution across those 465 definitions:

| Form | Count | Example |
| --- | --- | --- |
| Scalar name | string 130, number 78, address 12, bool 4 | `` > `tag`: string `` |
| **Literal union** | **89** | `` > `loglevel`: "debug" \| "info" \| "warning" \| "error" \| "none" `` |
| Array | 55 | `` > `rules`: [ [RuleObject](#ruleobject) ] `` |
| Link to an object | 41 | `` > `streamSettings`: StreamSettingsObject `` — the name written as a link to its page |

When enumerated values contain or order one another, each entry says so, so
nobody has to infer the hierarchy:

> - `"debug"`：调试程序时用到的输出信息。同时包含所有 `"info"` 内容。
> - `"info"`：运行时的状态信息等，不影响正常使用。同时包含所有 `"warning"` 内容。
> - `"warning"`：发生了一些并不影响正常运行的问题时输出的信息，但有可能影响用户的体验。同时包含所有 `"error"` 内容。
> - `"error"`：Xray 遇到了无法正常运行的问题，需要立即解决。
> - `"none"`：不记录任何内容。

## The default always says what it does

`默认值为` and `默认为` appear 101 times, and they are almost never left bare.
The value is followed by a gloss of the behaviour:

> 默认值为 `"0.0.0.0"`，表示接收所有网卡上的连接.

> `bytesPerSec` 默认为 0 **即不启用**

> 默认值为 `false` **即不转化**

> 默认为 0，**即不发送**

Template: `默认值为 X，即/表示 <behaviour>。` / `Default `X` — <behaviour>.`
Never `Default: false` and nothing else.

## Answer "what if I leave it out"

This is the question readers actually arrive with. The phrase 「省略或者填 0 时」
appears 41 times. Every optional field answers it.

> `concurrency`: number
>
> 最大并发连接数。最小值 `1`，最大值 `128`。省略或者填 `0` 时都等于 `8`, 大于 `128` 的值都将视为 128, 因为当一个连接达到最大复用次数 128 后其将不会再被分配任何新的子连接。

Semantics, lower bound, upper bound, omitted behaviour, out-of-range behaviour,
and the reason for it — one paragraph, no headings.

## Matching rules get a counter-example

Anything that matches, prefixes or globs is documented with something it
matches **and** something it does not, and the near-miss sits right on the
boundary:

> - 子域名 (推荐)：由 `"domain:"` 开始，余下部分是一个域名。当此域名是目标域名或其子域名时，该规则生效。例如 "domain:xray.com" 匹配 "www.xray.com" 与 "xray.com"，但不匹配 "wxray.com"。
> - 子串：由 `"keyword:"` 开始…例如 "keyword:sina.com" 可以匹配 "sina.com"、"sina.com.cn" 和 "www.sina.com"，但不匹配 "sina.cn"。

`wxray.com` against `www.xray.com` is chosen precisely because it is the one
people confuse. A counter-example that is obviously different teaches nothing.
Note also the inline `(推荐)` — the recommendation lives on the option, not in a
paragraph below.

## Examples are skeletons, not files

Reference JSON in the corpus has a median of **12 lines** — one object with
every field present, surrounding context elided as `"// ...": ""`. It is a
field checklist, not something to run. Runnable configurations belong in usage
guides.

```json
{
  "// ...": "",
  "balancer": {
    "strategy": "leastPing",
    "probe_url": "https://www.gstatic.com/generate_204",
    "probe_interval_s": 60
  }
}
```

No diagrams. All 12 mermaid diagrams in the corpus are in the tutorial layer,
none in the reference. **A diagram explains a mechanism; it does not list
fields.**

## Voice: no person, and passive is fine

Measured, the reference layer is where the writing is least personal — and this
is deliberate, not stiffness:

| Layer | "你/您" | English "you" | English passive |
| --- | --- | --- | --- |
| Reference | **2.0%** | 6.1% | **16.8%** |
| Beginner guide | 19.7% | 27.3% | 6.5% |

The subject is the field, not the reader: 「此规则生效」/「核心将回到单连接状态」,
"the rule then applies", not "you will then find that the rule applies". What
happens to a value matters more than who does it, which is what passive voice
is for.

## Sentence templates

Reuse the wording, not just the shape. Frequencies are from the corpus.

| Situation | Chinese | English | Count |
| --- | --- | --- | --- |
| Field header | `> \`name\`: type` | same | 465 |
| Enum type | `> \`x\`: "a" \| "b" \| "c"` | same | 89 |
| Array type | `> \`x\`: [ [XObject](#xobject) ]` | same | 55 |
| Default | `默认值为 \`X\`，即<行为>。` | ``Default `X` — <behaviour>.`` | 101 |
| Omitted | `省略或者填 \`0\` 时，<行为>` | `Omitted or `0` means <behaviour>.` | 41 |
| Required | `必填，<怎么得到它>。` | `Required, <how to get it>.` | 14 |
| Optional | `选填，<一句话>。` | `Optional, <one sentence>.` | 12 |
| Conditional | `当<条件>时，<结果>` | `When <condition>, <result>.` | 153 |
| Rule fires | `当此<X>匹配<Y>时，该规则生效。` | `This rule applies when <X> matches <Y>.` | 12 |
| Match example | `例如 "X" 匹配 "A" 与 "B"，但不匹配 "C"。` | `` `X` matches `A` and `B`. It does not match `C`. `` | — |
| Equivalence | `` `A` 等价于 `B` `` | `` `A` is the same as `B`. `` | 6 |
| Format | `格式为 \`x:y\`，形如 \`"..."\`` | `` Formatted `x:y`, as in `"..."`. `` | 34 |
| Purpose | `X 用于<做什么>。` | `X is used to <do what>.` | 192 |
| Varies by case | `具体的配置内容，视协议不同而不同。详见每个协议中的 \`XxxObject\`。` | `The contents depend on the protocol; see each protocol's \`XxxObject\`.` | — |
| Version change | `注：v25.7.26 后才将<行为 A>，在此之前都是<行为 B>。` | `Since v25.7.26, <A>; before that, <B>.` | — |
| Cross-reference | 有关\<X\>更详细的解析：加一个链接。 | In detail: a link. | — |
