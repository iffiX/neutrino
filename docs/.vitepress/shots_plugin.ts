import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { imageSize } from "image-size";
import type MarkdownIt from "markdown-it";

type Token = ReturnType<MarkdownIt["parse"]>[number];

const PUBLIC_DIR = resolve(process.cwd(), "public");
const PORTRAIT_BELOW = 0.8;
const PHONE_CROP = /_phone\.\w+$/;

interface Shot {
  src: string;
  alt: string;
  caption: string;
  width: number;
  height: number;
}

/** Reads one picture of a row: its address, description, caption and size. */
function readShot(md: MarkdownIt, token: Token): Shot {
  const src = token.attrGet("src") ?? "";
  const size = src.startsWith("/")
    ? imageSize(readFileSync(resolve(PUBLIC_DIR, `.${src}`)))
    : null;
  return {
    src,
    alt: md.renderer.renderInlineAsText(token.children ?? [], md.options, {}),
    caption: token.attrGet("title") ?? "",
    width: size?.width ?? 1280,
    height: size?.height ?? 800,
  };
}

/** Writes a row of pictures with one height, each as wide as its own shape. */
function renderRow(md: MarkdownIt, shots: Shot[]): string {
  const escape = md.utils.escapeHtml;
  const isPortrait = (shot: Shot) =>
    shot.width / shot.height < PORTRAIT_BELOW || PHONE_CROP.test(shot.src);
  const allPortrait = shots.every(isPortrait);
  const isAlone = shots.length === 1 && !allPortrait;
  const kind = allPortrait
    ? shots.length > 1
      ? " phones"
      : " solo-phone"
    : "";
  const figures = shots.map((shot, index) => {
    const number = shots.length > 1 ? `<i>${index + 1}</i>` : "";
    const caption = shot.caption
      ? `<figcaption>${number}${escape(shot.caption)}</figcaption>`
      : "";
    const shape = (shot.width / shot.height).toFixed(3);
    const cap = isAlone ? `;max-width:${shot.width}px` : "";
    return (
      `<figure style="--r:${shape}${cap}">` +
      `<img src="${escape(shot.src)}" alt="${escape(shot.alt)}" ` +
      `width="${shot.width}" height="${shot.height}" loading="lazy">${caption}</figure>`
    );
  });
  return `<div class="shots${kind}">${figures.join("")}</div>\n`;
}

/**
 * Turns a paragraph holding only images into a row, as `layout.md` describes.
 * A lone phone picture outside a step moves before the paragraph above it, which then sits to its left.
 */
export function shotsPlugin(md: MarkdownIt): void {
  md.core.ruler.after("inline", "doc_shots", (state) => {
    const tokens = state.tokens;
    for (let at = tokens.length - 2; at > 0; at -= 1) {
      const inline = tokens[at];
      if (
        inline.type !== "inline" ||
        tokens[at - 1].type !== "paragraph_open" ||
        tokens[at + 1].type !== "paragraph_close"
      ) {
        continue;
      }
      const parts = (inline.children ?? []).filter(
        (child) =>
          child.type !== "softbreak" &&
          !(child.type === "text" && !child.content.trim()),
      );
      if (!parts.length || !parts.every((child) => child.type === "image")) {
        continue;
      }
      const block = new state.Token("html_block", "", 0);
      block.content = renderRow(
        md,
        parts.map((part) => readShot(md, part)),
      );
      block.level = tokens[at - 1].level;
      tokens.splice(at - 1, 3, block);
      const isBesideText =
        block.level === 0 &&
        block.content.startsWith('<div class="shots solo-phone">') &&
        tokens[at - 2]?.type === "paragraph_close" &&
        tokens[at - 4]?.type === "paragraph_open";
      if (isBesideText) {
        tokens.splice(at - 1, 1);
        tokens.splice(at - 4, 0, block);
      }
    }
    return true;
  });
}
