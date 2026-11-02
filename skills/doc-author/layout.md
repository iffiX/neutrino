# Page layout

Page layout is how a finished guide page looks on screen: where each picture sits,
how large it is, and how the reader moves through it. The reader alternates between
a wide panel and a tall phone, so the layout decides this for them; a writer never
sizes a picture by hand. What a page holds is in `outline.md`.

## Pictures

| Rule | Reason |
| --- | --- |
| Every step of installing and of using something has a picture, placed right after the step's text. | The reader matches the page against the screen, and a step with no picture is where they stop. |
| Every picture shows the light theme: panel, setup wizard, client, phone and third-party sites, whatever the product's own default is. The capture tool switches the theme; the product does not change for the docs. A terminal is text, never a picture. | The site is dark, and a dark screenshot on a dark page cannot be read. Mixed themes read as different products. |
| Every picture comes from the international edition. | One set of pictures is all a reader has to match. |
| Every panel picture is taken at the same window size and density, 1280 by 800 at 2x. Every phone picture is taken at 1080 by 2400. | The same control keeps the same size on every page. |
| A section's first panel picture shows the whole page. Later pictures in that section are cropped to the area being used. | The whole page tells the reader where they are, and a crop lets them read the words. |
| One picture marks one control, in the same red box. | A second box leaves the reader guessing which to press first. |
| The same names appear everywhere: system `my-computer`, account `lab`. | A name that changes between pictures reads as a different machine. |
| No picture holds a real client QR code, key, token, password or public address. | Pictures are published, and a client link carries keys. |
| Words the reader needs are in the text as well as the picture; a picture's description says what it shows. | A picture does not load everywhere, and search and screen readers read the text. |

## The arrangements

Pictures in a row share one height, and each one's width follows its own shape. A
page uses only these arrangements.

| The step shows | Arrangement | Why |
| --- | --- | --- |
| One whole panel page | The full content width | The reader needs to read a whole screen. |
| Two steps in a row on the panel | Two pictures side by side, a caption under each | The reader sees the action and its result without scrolling. |
| The panel and a phone working together | One row, the panel wide and the phone narrow, same height | The relation between the two screens is the point. |
| Several steps in a row on a phone | At most four in a row, a caption under each | A phone is narrow, and one per row wastes a screen on each step. |
| One phone picture | Text on the left, the phone on the right, 190 px wide | The empty space beside a tall picture is the reason phone steps feel endless. |
| Several state screens that are mostly blank | A table, one state per row: a small picture, the words on the screen, the cause and what to do. Each picture is cropped to its content, and all use one crop size. | The blank says nothing, and the reader compares states in one view. |

A row holds at most two panel pictures, or one panel picture and one phone, or four
phones. A row's pictures belong to one logical sequence; unrelated pictures never
share a row just to save space.

On a screen narrower than 640 px, a row stacks one picture per line, phones go two
per line, and the text comes before its picture.

## Writing them in Markdown

A writer writes standard Markdown, and the site's build does the rest.

```md
1. 按 **+ 添加模块**，再勾选要安装的应用。

   ![添加模块按钮标红](/guide/zh/deploy_x_01.webp "按 + 添加模块")
   ![code-server 卡片标红](/guide/zh/deploy_x_02.webp "勾选 code-server")
```

| Written | Becomes |
| --- | --- |
| Image lines with no blank line between them | One row |
| The image's title, in quotes | The numbered caption under it |
| A single portrait image in a step | The picture to the right of the step's text |
| An image inside a table cell | A small picture, 220 px wide, that still opens larger |
| Text between square brackets | The description for search and screen readers, shown when the picture is enlarged |

The build reads each picture's size, so a row keeps its shape while pictures load
and the page does not jump. Pictures below the first screen load when the reader
reaches them.

## Enlarging

Every picture opens larger on a click. In the enlarged view the arrow keys and a
swipe move through all the page's pictures in order, a pinch zooms on a phone, and
the description shows below. Escape, the close button or a click outside closes it.

## The facts strip

A page about one feature shows one small row right after its opening line, with
coloured chips: the supported systems, the supported editions, and the Neutrino
version that first has the feature. A system or edition it lacks stays in the row,
struck through and grey, so the reader sees the absence at once.

```md
<Facts systems="Linux,macOS" editions="国际版,国内版" since="0.5.0" />
```

A choice inside a page, such as the network modes, states the same facts in columns
of its own table.

## Steps

A numbered list renders as a rail: a numbered circle per step and a line joining
them, so a picture never hides which step it belongs to. Steps that one row of
pictures can show together count as one numbered step when they are one action on
one screen.

## The rest of the page

| Item | Rule | Reason |
| --- | --- | --- |
| Line length | Text is at most 720 px wide, while pictures can use the whole content width. | Long lines are hard to follow, and pictures need the room. |
| Right-hand outline | A page with headings shows it beside content up to 800 px wide. | The reader of a long page needs to see where they are. |
| Commands | A code block with a copy button, and output in its own `text` block. | A reader copies a command, and a picture of text cannot be copied or searched. |
| A difference between systems | Tabs for Windows, macOS and Linux when a step differs. A one-sentence difference stays in the sentence. | A reader on one system never reads the others. |
| Something most readers skip | Folded under a title that says what is inside. | The main path stays short, and the detail stays one click away. |
| A table | Used for options, comparisons and states, never to hold steps. | A step in a table cell has no room for its picture. |
| Theme | The site opens in the dark theme, and the reader can switch. The online demo stays light. | Dark is the product's default look, and light pictures stand out on it. |
| Moving on | Each page has previous and next links at its foot, in sidebar order. | The reader of a sequence never has to go back to the sidebar. |

## Checks

- Each step of 安装 and 使用 has a picture, or a placeholder listed in the page's notes.
- No picture is dark.
- No row breaks the limits above.
- The page reads correctly at 1920, 1440 and 390 px wide, with no sideways scroll.
- Every picture opens larger, and the arrow keys walk the page's pictures in order.
