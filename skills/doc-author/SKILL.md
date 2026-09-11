---
name: doc-author
description: Writing standard for every Markdown document in this repository, in English and in Chinese. It covers README.md and README.zh-CN.md, the VitePress guide under docs/guide/ (quick start, overview, feature guides, CLI reference, troubleshooting), the design pages and coding rules under skills/core-code-author/, and the state notes in docs/memory.md. Load it before drafting, rewriting or reviewing any of these, whenever a request mentions a README, a guide page, a quick start, a reference, troubleshooting, a design page or state notes, and before any request to translate documentation, because the two languages are written independently from one outline and nothing is translated.
---

# Writing a document

A document in this repository is one page of one kind, for one reader, in one
language, written from an outline the user approved. This file is the gate
before drafting and the check after it. The register of each language is in
its own file; the shape of each kind of page is in `kinds.md`.

## Before the first sentence

Every question below has an answer written down before drafting starts. The
answers are the outline, and the outline is the only thing the two language
writers share. A page written without these answers takes a different shape in
each language and drifts between kinds.

| Question | The answer names | Why it is settled first |
| --- | --- | --- |
| Which kind of page? | One row of the kind table below. | Each kind refuses what its neighbours do; mixing them is the main cause of unusable pages. |
| Who reads it? | One reader: what they run, what they already know. | Person, term choice and depth all follow from the reader. |
| What can the reader do at the end? | One outcome, stated as a state of the system or of the reader. | It becomes the opening sentence and the pass condition of the reader test. |
| What is out of scope? | The neighbouring topics the page links to instead of covering. | Scope creep turns a guide into a reference and a reference into a tutorial. |
| Which outline? | Headings, in order, one line each on what each section holds. | The user approves the outline before prose exists, so both languages build the same page. |

Present the outline and wait for approval. Skipping the wait is the failure
this gate exists for.

## The kinds

Two questions place a page. Does it serve the reader's action or the reader's
understanding? Does it serve learning or does it serve work? The answers give
one row of the table below for every document here. Per-kind shape and checks
are in `kinds.md`.

| Kind | Serves | Answers | What it refuses | Documents here |
| --- | --- | --- | --- | --- |
| Tutorial | action, learning | "Can you get me to a working X?" | choices, explanation, abstraction, options the learner does not need | quick start |
| How-to guide | action, work | "How do I do X?" | teaching basics, explaining why, completeness, embedded reference lists | feature guides, troubleshooting, the install section of the README |
| Reference | understanding, work | "What is X?" | instruction, explanation, opinion, marketing | CLI reference, state notes, the option tables inside guides |
| Explanation | understanding, learning | "Why is X like this?" | steps, exhaustive detail, anything the reader must do | overview, design pages, the folded architecture section of the README |

The landing README is a composite: a one-paragraph explanation, an install
how-to, and links. Its own section in `kinds.md` says how much of each.

## Rules every document obeys

Each rule is a sentence a reviewer can check. Each has its reason, because
a rule without one gets negotiated away under deadline.

| Rule | Reason |
| --- | --- |
| Present tense throughout; nothing about what the product did or will do. | The page describes what exists now; a promise ages into a false statement. |
| The reader is addressed directly (`you` in English, `你` in Chinese); the writer is absent: no `we`, `let's`, `us`, `我们`, `让我们`. | The writer is not beside the reader. |
| The first paragraph states what the thing is, or what the reader has at the end. | The reader decides in one paragraph whether the page is theirs. |
| The page has no summary, recap, closing line, or "next steps" paragraph. | A recap repeats the page; a closing line becomes a refrain stamped on every page. |
| A machine does what it performs: returns, writes, starts, stops, rejects with a code. It never waits, wants, asks, answers, decides or refuses in prose. | Volition handed to a program hides which component acts and reads as machine-written prose. |
| A backend refusal is quoted as its code in code font; an English or Chinese gloss follows only once. | The reader searches the code, and the code is what the interface shows. |
| A UI label is bold, spelled as the interface shows it, in the page's language; a Chinese page adds the English label in parentheses at first use. | The reader matches the page against the screen. |
| A placeholder is `<kebab-case>` inside code only, defined at first use; prose names the thing instead. | Bare angle brackets in prose render as HTML tags, and an undefined placeholder is a guess. |
| Every ordered list item is written `1.` and the renderer numbers it; a procedure has one action per item. | Hand numbering diverges between the two languages and breaks on edit. |
| Headings use sentence case, end without punctuation, go no deeper than H4, skip no level, never stand as a lone child, and never repeat the parent's name. | Headings are the navigation; irregular ones break scanning and the sidebar. |
| An alert follows no other alert, holds at most four lines, and a section has at most one. | Stacked alerts cancel each other. |
| Link text is the target's title or subject in a sentence of its own; never `here`, `this page`, `这里`, `此处`. | The reader scans links out of context. |
| A code block names its language, shows no `$` prompt, and shows output in a separate `text` block. | The reader copies the block; a prompt or mixed output breaks the paste. |
| No em dash inside a sentence, in either language; a comma, a period or parentheses do the work. | The dash is the single strongest machine tell, and each authority here bans it. |
| No security reassurance of the form "X never leaves the machine". | A claim stated as an absence is untestable by the reader and reads as marketing. |
| Each sentence pattern from `english.md` or `chinese.md` appears at most once per page. | A pattern used twice is a template; used ten times it is the page. |
| The two languages share the outline and nothing else; each is written from its own register file, never from the other language's text. | A sentence carried across languages keeps the source language's clause order. |
| Product terms are fixed: hub, agent, client in English; 微子, hub or 中枢, 被控端, 客户端 in Chinese; never 中微子. | One name per thing across thirty pages. |

## Budgets

A budget is a per-page limit, so a reviewer can count it. Ratios observed across
a site are not budgets.

| Item | Limit | Source |
| --- | --- | --- |
| English sentence | 25 words, two clauses | Astro, Microsoft |
| Chinese clause | 20 characters; 30 to 39 only when unambiguous; 40 never; a comma-chained sentence 100 characters | 阮一峰 句子 |
| Paragraph | four sentences in English; seven lines, best four, in Chinese | Microsoft, 阮一峰 段落 |
| Steps in one procedure | nine; split at a heading beyond that | yikeke 列表, Microsoft |
| Step result sentence | only when the outcome is invisible to the reader | GitHub procedural steps |
| Alerts | one per section, three per page, four lines each, never consecutive | GitHub, GitLab, yikeke |
| Links | two per section, each in its own sentence | GitHub |
| Heading depth | H2 to H4 | GitLab, 阮一峰 标题 |
| Any one sentence pattern | once per page | the old skill's refrain failure |

## Before calling it done

Run `checklist.md` line by line; half of it is a grep. Then run the reader
test, which catches what a grep cannot:

1. Write five questions the intended reader asks of this page, including one the
   page answers only by implication.
1. Give the page alone, with no conversation context, to a fresh reader: a
   subagent when one is allowed, otherwise a new conversation.
1. Ask for each answer, what was ambiguous, and what the page assumed the reader
   already knew.
1. Fix the sections that produced a wrong answer or an assumption, and repeat
   until the reader answers every question from the page alone.

## Rationalisations that end badly

| Thought | What is true |
| --- | --- |
| "The outline is obvious, I'll draft straight away." | The other language's writer has a different obvious outline. Write it down. |
| "This warning matters, it needs its own alert." | One alert per section. A second one goes under a heading as body text. |
| "A result sentence after every step helps." | It restates the step. Add it only where success and failure look alike. |
| "A short recap helps the reader leave." | The reader leaves at the last step. A recap becomes the refrain on every page. |
| "The Chinese page is nearly the English one, I'll render it." | A rendering keeps English clause order and the 被 passive. Write from the outline. |
| "This sentence pattern fits every entry." | That is how a page becomes twenty-five copies of one sentence. Once per page. |
| "The reader test is overkill for a small page." | Small pages hide assumptions best. Five questions take two minutes. |

## Red flags in your own draft

A colon at the end of a heading. A count followed by a list ("three ways to").
A sentence pivoting on "not X but Y". A fact stated as an absence ("no setup
needed"). A machine that waits, asks or refuses. Two alerts in sight of each
other. A paragraph starting "Note that". A Chinese sentence with 被 in it. Any
of these means the draft goes back through the register file before review.

## Files

| File | Open it when |
| --- | --- |
| `english.md` | Writing any English page: register, step shape, banned words and shapes, sentence patterns. |
| `chinese.md` | 写任何中文页面：语气、句子、排版、禁用词、禁用句式、句式范例。 |
| `kinds.md` | Shaping a page: reader, opening, structure, refusals and checks for each kind written here. |
| `checklist.md` | Finishing a page: the line-by-line check, with the grep for each mechanical item. |
