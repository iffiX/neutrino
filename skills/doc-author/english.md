# English register

An English page here reads as a native technical writer's page, in the register
the Google, Microsoft, GitHub and GitLab guides describe. Nothing in it is a
rendering of a Chinese sentence.

## Authorities

| Guide | What it settles here |
| --- | --- |
| Google developer style | present tense, second person, conditions before instructions, no future features |
| Microsoft style | the step shape, verbs first, brevity, sentence-case headings |
| GitHub docs style | procedure order, placeholders, alerts, code blocks, link text |
| GitLab word list | the banned words and their reasons, no em dash |
| Diátaxis | which sentences belong to which kind of page |
| vale-ai-tells | the named sentence shapes that mark machine prose |
| humanizer:humanizer (upstream `blader/humanizer`) | one pass over the whole page after drafting; it removes padding and never swaps a term for an everyday word; where it differs from this page, the stricter rule holds |

## Voice

| Rule | Reason |
| --- | --- |
| Present tense; `will` only for an event at a stated later moment. | The page describes standing behaviour, and a future promise ages. |
| Second person for the reader; a reference entry addresses nobody and states facts. | Person drifting between pages has no principle behind it. |
| The writer is absent: no `we`, `us`, `let's`, `I`. | The writer is not beside the reader. |
| Active voice, with the acting component named. | Passive hides which component acts. |
| An instruction is an imperative sentence. `You can` states an option only. `You should` never appears; a requirement says `must`, an option says `can`. | `should` leaves the reader asking what happens if not. |
| At most 25 words and two clauses per sentence; at most four sentences per paragraph. | Longer sentences hide the verb; longer paragraphs hide the point. |
| Sentence-case headings, no end punctuation, no bold inside. | Headings are scanned in a sidebar. |

## The step shape

A procedure is an ordered list introduced by one line ending in a colon, with
its prerequisites stated before the list, never inside a step.

| Inside one step | Rule |
| --- | --- |
| Order | optional marker, then condition or location, then the action, then the result |
| Marker | `Optional:` at the start when the step can be skipped |
| Condition or location | first, as a short clause: `In the **Network** panel,` or `If the box has one interface,` |
| Action | one imperative verb, one action; a menu path is `**A** > **B**` |
| Result | only when success and failure look alike to the reader; in the same paragraph as the action |
| Form | a complete sentence with a period; markup `1.` on every item |
| Count | at most nine steps; a longer task splits at a heading |
| Single step | one bullet |

`Select` for anything on a screen; `run` for a command; `open` for a page or
file. `Click` and `navigate to` do not appear.

## Placeholders, code and output

| Item | Rule |
| --- | --- |
| Placeholder | `<kebab-case>` inside a code span or block; the sentence before its first use says what replaces it |
| Placeholder in prose | never; the sentence names the thing (`the hub address`) |
| Code block | opens with a language tag (`bash`, `json`, `text`); no `$` prompt |
| Output | its own `text` block after the command block; long output cut with `...` on its own line |
| Inline code | commands, flags, file paths, config keys, codes, values the reader types |
| UI label | bold, exactly as the interface shows it |
| Refusal code | in inline code, quoted exactly; a one-clause gloss after it once |

## Banned words

| Word | Reason | Use instead |
| --- | --- | --- |
| simply, simple, easy, easily, just, obviously | tells a stuck reader they are slow | delete |
| please | a step is not a request | delete |
| note that, it is worth noting, keep in mind | announces instead of stating | delete the phrase, keep the fact |
| currently, at the moment, for now | dates the page | delete; the page is now |
| in order to | filler | `to` |
| utilize, leverage | formal register | `use` |
| via | vague preposition | `through`, `with`, `by` |
| e.g., i.e., etc. | abbreviations read badly aloud and in translation | `for example`, `that is`, list the items |
| once (as "after") | ambiguous with "one time" | `after`, `when` |
| may, might | reads as doubt | `can` for ability, `must` for a requirement |
| should | ambiguous between advice and requirement | `must`, or state the consequence |
| allow, enable (as "lets you") | passive framing of a feature | name what the reader does |
| above, below | breaks when content moves | `earlier`, `following`, or a link |
| and/or | ambiguous | `or`, or both cases spelled out |
| robust, seamless, powerful, comprehensive | unmeasured adjectives | the number, the list, or delete |
| delve, harness, embark, landscape, tapestry | machine vocabulary | plain verb or delete |

## Banned sentence shapes

Each name is a rule in vale-ai-tells. Recognise the shape, then rewrite the
whole sentence. A swapped word keeps the shape.

| Shape | Recognise it by | Do instead |
| --- | --- | --- |
| Counted lead-in | "three things", "two ways", then a list | drop the count; the list shows its length |
| Contrastive pivot | "not X, but Y", "rather than X", "X, not Y" | state Y; X was never proposed |
| Negated fact | "no configuration is required", "needs no database", "never leaves" | state what is present, or delete |
| Stacked absence | "No X. No Y. No Z." | one sentence with the positive fact |
| Anthropomorphism | the daemon waits, wants, decides, refuses, answers | the verb it performs: returns, rejects with code, exits |
| Graded mechanism | "brittle", "benign", "smart" on a component | the measurable property |
| Trailing participle | ", making every read a miss", ", ensuring consistency" | a second sentence with its own subject, or delete |
| Shell noun copula | "The problem is that", "The point is" | state the fact as the sentence |
| Label and explain | "The takeaway: always test." | a sentence with a verb |
| Announcement heading | "What you'll learn", "Overview of this page" | a heading naming the content |
| List introduction | "Here's a breakdown", "Below you'll find" | the introducing line names the list's subject and ends in a colon |
| Hedge stack | "could potentially", "may possibly", "it's important to note" | one modal or none |
| Formal transition | "Moreover", "Furthermore", "Additionally" at sentence start | delete; order the sentences instead |
| Sequencing marker | "Firstly", "Secondly", "Finally" | an ordered list, or plain sentences |
| Conclusion marker | "In conclusion", "Ultimately", "In short" | delete the paragraph |
| Rhetorical self-answer | "The catch? ..." , "Why? Because" | state the fact |
| Verb tricolon | "build, test, and deploy" as the default rhythm | the actual number of items |
| Mic drop | "It matters." "Full stop." | delete |
| Figurative verb | mints, rides, travels, lives, owns, carries, earns, lands, surfaces, fires, clears, ships (for a release), wires, stands (for exists), hands out, spins up, lights up, bakes in | generates, is sent, is in, has, includes, returns, appears, is released, exists, gives |
| Unbaselined comparison | "significantly faster", "much lower" | the number, or delete the adverb |
| Self reference | "as mentioned above", "as we'll see", "this page explains" | a link, or delete |

Over-correction is its own tell. A rewrite subtracts and sharpens; it adds no
first person, no invented numbers, and no manufactured stakes. Sentences of
varied length stay.

## Manual anti-patterns

A manual page is technical documentation. The reader wants to know what a thing
is and how to use it. These failures were found in a draft of the manual.

| Anti-pattern | Bad | Do instead |
| --- | --- | --- |
| Headless opening: the first sentence under the title has no subject | "Deploy apps on your own computer, use them safely from anywhere, and share them too." | Start with the thing the title names and say what it is, or speak to `you`: "Neutrino Hub is an open source, self-hosted panel for deploying apps." |
| Topic list as an opening | "How the hub, the agent and the client fit together, and where a connection goes." | State the content: "A device connects to one port on the hub, and the hub checks permissions and connects to the app." |
| Question as a hook | "Have a public address? Your phone connects straight back." | A condition: "If your connection has a public address, you can use Direct." |
| Causative definition | "File sharing turns a folder into a drive on your laptop." | `X is`, in one sentence: "File sharing is the feature that mounts a folder on your system at a path or drive letter on the client for direct reading and writing." |
| Parallel items packed into a paragraph | "Home shares share the account's own folder, such as `/home/lab`. Folder shares share one folder you choose." | Name the kinds in the introducing line, then one bullet each. |
| Talking to nobody: the page discusses itself | "The design fits in one sentence." "This page walks through each step." | Delete; state the fact, and use `you` when the reader acts. |
| Living object: a device does what only a person can | "This device must first install the client." | The person is the subject: "Install the client on this device." A program does only what it performs. |
| Everyday word for a term | "The phone recognises the hub by the key in the link." | The term the field uses, from the following table. |
| One-word answer | "Nothing." | A full sentence with the mechanism: "The hub sends no reply when the first bytes are wrong, and closes the connection after 5 to 30 seconds." |
| Advertising a third party | "No server to buy: open a free account and people outside can open your links too." | What it is and how the hub uses it: "SakuraFrp is a third-party tunnel service. The hub runs frpc, which connects to a SakuraFrp node, and the node forwards connections." The free quota goes in a small table after the opening, with its reading date and no selling point. |
| Sales tone from the home page | "Everything at a glance, no clicking around." | What the page shows and how to reach it: "**Dashboard** shows traffic, systems and AI usage." |
| Colloquial from top to bottom on a security or architecture page | "Can other programs on my computer get at it?" | Plain answers go in one section, `Quick answers`. `Technical architecture` is for technical readers and holds the protocol, the routing and the architecture diagram. |
| Stating protection thresholds, which help someone tune an attack | "Each connection is read for 20 to 100 bytes and held for 5 to 30 seconds. At most 128 connections wait for admission." | State the mechanism and leave out any number the reader can do without: "The hub reads a random number of bytes, holds the connection for a random time, then resets it. Connections awaiting admission have a limit." A number the reader acts on stays, such as a link valid for 30 minutes. |
| Stating a date, when the page describes the product as it is now | "These results were measured on 2026-10-26." | Delete the date: "The measured results are:" Only a table surveying vendors states a reading date. |
| A feeling as a condition | "Changed your mind?" | "If you no longer need it" |
| `Same as above` in a table | "Same as above" | Write the content in full. |
| Definition with a sales tail | "code-server is the open source web VS Code, no Microsoft terms, write code on your phone." | End the definition at the period. The next fact is its own sentence, addressed to `you`. |
| One thing under several names | "Open a road back to the hub when you are out." | One name per thing, the name the interface shows. |
| Dangling reference: it, that side, the other end | "When that side connects, the app tries again." | Name the noun: "When NetBird or EasyTier connects, the app tries again." |
| Misplaced subject | "Share visitors keep no record." | The acting component is the subject: "The hub keeps no record of a visitor's identity or address." |
| Empty lead-in | "The statuses go like this." | Name the subject in a line ending in a colon: "Each status means:" |
| Colloquial heading | "What's different", "Later", "Try it", "Careful" | A heading naming the content: "Differences", "Maintenance", "Verify the connection", "Risks". |
| Guessing at a cause | "Most likely the link expired." | "The usual cause is an expired link." |
| Assuming where the reader is | "The rest stays on your home line." | Name the thing: "The rest uses this computer's own connection." |
| Answering half the question | A question about two products, answered for one. | Answer every part. |

### Terms

Prose uses the right-hand word. A label quoted from the interface stays bold and
exact, whatever this table says.

| Do not write | Write |
| --- | --- |
| lock, secret (for a key) | key, public key, private key |
| recognise, tell | verify, authenticate |
| touch, get at, reach (for data) | access, read, write |
| guard, watch (a port) | listen on |
| opening bytes, knock | magic bytes |
| door | port, endpoint |
| dial | connect to |
| run many streams over | multiplex |
| stuff, materials | the named thing, such as a setup key or a network key |
| friends, classmates | visitor, the other person |
| says, reads (for a status) | shows |
| comes back | returns, restores |
| road, way back | the interface's name, or connection method |
| by itself (of a program) | automatically |
| one copy (of a running program) | one instance |
| sealed | encrypted |
| tick | select |

## Sentence patterns

Each is an example, fits the situation named, and appears at most once per
page. Reuse the shape and none of the words.

| Example | Fits |
| --- | --- |
| `nhub apply --dry-run` renders every module and changes nothing on the system. | the first line of a reference entry |
| Once the agent is installed, the machine appears on the Agents page, and every step below happens there. | the opening of a how-to guide (each page writes its own; never this sentence on two pages) |
| Before you start, the hub must be reachable from this machine. | a prerequisite line above a procedure |
| In the **Network** panel, select **Apply**. | a step inside the interface |
| If the box has one interface, skip this step. | a conditional step |
| Run `sudo systemctl restart neutrino_hub_web`. The panel drops your session and asks you to sign in again. | a step whose result is invisible until stated |
| You can set the address in the panel or in `config/network/lan.json`. | stating an option, the one use of `you can` |
| The hub rejects the request with `token_expired` when the token is older than its lifetime. | a cause line in troubleshooting, with an example code |
| A profile is one named set of routes that the client applies as a whole. | a definition in reference or explanation |
| The panel keeps `config/` as the only source of truth so that a backup of it reproduces the appliance. | a design page stating a rule with its reason |
