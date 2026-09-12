# Completion check

Run every line before a page is called done. Lines marked `[grep]` run as a
command over the page; a hit is a finding to fix or to justify in the review.
Run the greps from the repository root with the page path as `$P`.

## Both languages

| Check | How |
| --- | --- |
| The opening paragraph states what the thing is or what the reader has at the end. | read the first paragraph |
| No summary, recap, closing line or next-steps paragraph. | read the last section |
| No em dash inside a sentence. `[grep]` | `grep -n '—' $P` |
| Every ordered item is `1.`; no hand-numbered bold steps. `[grep]` | `grep -nE '^\s*([2-9]|[1-9][0-9])\.\s|^\*\*[0-9]+[.、]' $P` |
| No alert follows another; at most one per section, three per page. `[grep]` | `grep -c '^::: ' $P` and `awk '/^:::$/{c=NR} /^::: /{if(c && NR-c<3) print FILENAME": "NR}' $P` |
| No alert longer than four lines. | read each alert |
| No heading ends in punctuation; none is bold; none deeper than H4. `[grep]` | `grep -nE '^#{1,4} .*[:.。：]$|^#{5,}|^#+ .*\*\*' $P` |
| No skipped heading level, no lone child heading, no child repeating its parent. | `grep -n '^#' $P` and read the outline |
| No `here` or `这里` as link text. `[grep]` | `grep -nE '\[(here|this page|这里|此处|点击这里)\]' $P` |
| Every code block has a language tag; none shows a `$` prompt. `[grep]` | `grep -nE '^```$|^\$ ' $P` |
| Placeholders appear only inside backticks. `[grep]` | `grep -nE '<[a-z]+(-[a-z]+)+>' $P` and check each hit is in code |
| Every refusal code on the page is in inline code and appears in the product. | list the codes, grep the backend for each |
| UI labels are bold and match the interface. | compare against the screen |
| No security reassurance. `[grep]` | `grep -nEi 'never (leaves|sends|stores)|不会(离开|上传|发送)' $P` |
| No future or past tense about the product. `[grep]` | `grep -nEi '\bwill\b|\bwould\b|planned|coming soon|used to|将会|即将|未来|计划' $P` |
| No writer in the text. `[grep]` | `grep -nEi "\bwe\b|\bus\b|let's|\bour\b|我们|让我们|笔者" $P` |
| No counted lead-in before a list. `[grep]` | `grep -nEi '\b(two|three|four|five) (ways|things|steps|parts|reasons|kinds)|[两三四五]个(方面|部分|原因|步骤)|分[两三四五]步' $P` |
| No contrastive pivot. `[grep]` | `grep -nEi '\bnot [^.]*, but\b|rather than|不是[^。]*而是|不在[^。]*而在' $P` |
| No sentence pattern from the register file used more than once. | grep the page for the shape of each pattern used |
| No opener shared across the site: the first sentence's first four words appear on no other page. `[grep]` | `for f in $(git ls-files 'docs/guide/**.md'); do awk 'NF && !/^(---|#|!|:::|title:)/{print substr($0,1,16); exit}' $f; done \| sort \| uniq -c \| sort -rn \| head` (every count is 1) |
| Product terms are the fixed ones. `[grep]` | `grep -n '中微子' $P` |
| The step budget holds: no procedure over nine items. | count each list |
| Each step has one verb and one action; a result sentence only where the outcome is invisible. | read each procedure |
| Sentence length: English 25 words and two clauses; Chinese 20 characters per clause, 40 hard cap. | read each long line |
| The two languages share headings one to one, and no sentence in one is a rendering of the other. | compare outlines |
| The reader test in `SKILL.md` has run and every question is answered from the page alone. | record the five questions and the outcome in the review |

## English only

| Check | How |
| --- | --- |
| Banned words. `[grep]` | `grep -nEiw 'simply|simple|easy|easily|just|obviously|please|currently|utilize|leverage|via|e\.g\.|i\.e\.|etc|and/or|robust|seamless|comprehensive|delve|harness|embark|landscape|tapestry' $P` |
| Announcing phrases. `[grep]` | `grep -nEi 'note that|worth noting|keep in mind|in order to|it is important' $P` |
| Modals. `[grep]` | `grep -nEiw 'should|may|might' $P` |
| Formal transitions and sequencing. `[grep]` | `grep -nEi '^\s*(moreover|furthermore|additionally|firstly|secondly|finally|in conclusion|ultimately|in short)' $P` |
| Absence framing. `[grep]` | `grep -nEi '\bno [a-z]+ (is|are) (required|needed)|needs no|without any' $P` |
| Figurative verbs on components. `[grep]` | `grep -nEiw 'mint(s|ed)?|rides?|travels?|lives?|owns?|carr(y|ies|ied)|earns?|lands?|surfaces?|fires?|clears?|ships?|wired?|stands?|hands? (out|down)|spins? up|lights? up|baked? in' $P` (read each hit; `your own` and `sit at` are literal) |
| Anthropomorphism. `[grep]` | `grep -nEi '(hub|agent|client|panel|daemon|service) (waits|wants|asks|answers|decides|refuses|knows|thinks)' $P` |
| Click and navigate. `[grep]` | `grep -nEiw 'click|navigate' $P` |
| `you can` only where an option is stated. `[grep]` | `grep -nEi 'you can' $P` and read each |
| Trailing participle after a comma. `[grep]` | `grep -nE ', (making|ensuring|allowing|leaving|giving) ' $P` |

## 仅中文

| 检查 | 方法 |
| --- | --- |
| 被字句（“被控端”除外）。`[grep]` | `grep -nP '被(?!控端)' $P` |
| 黑话与评价词。`[grep]` | `grep -nE '赋能|闭环|抓手|打通|沉淀|落地|底座|底层逻辑|生态|心智|收口|加持|极致|丝滑|一站式|深度集成|颠覆|重塑|很值得|最佳|最好|最先进|显然|真正|很清楚|很现实|很顺' $P` |
| 隐喻动词。`[grep]` | `grep -nE '铸|落在|递给|扛|背着|承载|站在|长在|跑在' $P`（「跑在」改「运行在」或「装在」） |
| 程度和数量词。`[grep]` | `grep -nE '很好地|较多|大量|一些|几乎|数倍|基本上' $P` |
| 过场句。`[grep]` | `grep -nE '聊到这里|接下来|先把|值得一提|下面(我们)?来看|综上|总之|以上就是' $P` |
| 反问句和感叹句。`[grep]` | `grep -nE '[？！]' $P` |
| 请与抱歉（“请求”“申请”除外）。`[grep]` | `grep -nP '(?<![申邀])请(?!求)|抱歉' $P` |
| “对……进行”。`[grep]` | `grep -nE '对.{1,12}进行' $P` |
| 的字链：一个名词前三个“的”。`[grep]` | `grep -nE '的[^，。；、]{1,10}的[^，。；、]{1,10}的' $P` |
| 中英之间空格；全角标点前后无空格。`[grep]` | `grep -nP '[\x{4e00}-\x{9fff}][A-Za-z0-9]|[A-Za-z0-9][\x{4e00}-\x{9fff}]| [，。；：）]|（ ' $P` |
| 括号：全英文内容半角并留空格，含中文内容全角不留空格。 | 逐个括号看 |
| 界面名加粗，首次出现括注英文。 | 对照界面 |
| 人称统一为“你”。`[grep]` | `grep -n '您' $P` |
| 中文标点在中文句子里，半角标点只在整句英文里。`[grep]` | `grep -nP '[\x{4e00}-\x{9fff}][,.;:!?]' $P` |
