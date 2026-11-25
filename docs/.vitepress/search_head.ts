import { existsSync } from "node:fs";
import { join } from "node:path";
import type { HeadConfig, PageData } from "vitepress";

/**
 * What search engines and link previews read of a page: its search title and
 * description from its frontmatter, the canonical address, the address of the
 * same page in the other language, and the preview card.
 */

const SITE = "https://neutrinohub.net";
const SOCIAL_IMAGE = `${SITE}/social_preview.png`;
const ENGLISH_PREFIX = "en/";
const SITE_NAME = { zh: "微子中枢", en: "Neutrino Hub" };

/** The description of a page whose frontmatter names none, and of the site. */
export const DEFAULT_DESCRIPTION = {
  zh: "微子中枢把要用的软件一键部署到你自己的电脑上，手机和笔记本随时打开，发个链接就能分享。",
  en: "Neutrino Hub deploys apps on your own computer in one click and opens them from your phone and laptop anywhere.",
};

/** The home pages' search title and description, which replace the page's own. */
const HOMES: Record<string, { title: string; description: string }> = {
  "index.md": {
    title: "微子中枢：一键部署 AI 应用，走到哪用到哪",
    description:
      "微子中枢把写代码的 AI 工具、AI 助手、聊天机器人和本地大模型一键装到你的电脑上，一个 AI 网关管好密钥，手机和笔记本随时打开。",
  },
  "en/index.md": {
    title: "Neutrino Hub: deploy AI apps in one click, use them anywhere",
    description:
      "Neutrino Hub installs AI coding tools, AI assistants, chat bots and local models on your computer in one click, with one AI gateway for the keys.",
  },
};

/** A page file's address: "deploy/vscode.md" is /deploy/vscode, "en/index.md" is /en/. */
function pageUrl(relativePath: string): string {
  const path = relativePath.replace(/\.md$/, "");
  if (path === "index") {
    return `${SITE}/`;
  }
  if (path.endsWith("/index")) {
    return `${SITE}/${path.slice(0, -"index".length)}`;
  }
  return `${SITE}/${path}`;
}

/**
 * Sets the home pages' search title and description, a description for a
 * page that names none, and adds each page's canonical, language and preview
 * tags to its head.
 *
 * Args:
 *   pageData: The page, changed in place.
 *   srcDir: The folder the page files live in.
 *   forSearch: Turns shown words into the words a search reads.
 */
export function searchHead(
  pageData: PageData,
  srcDir: string,
  forSearch: (text: string) => string,
): void {
  const file = pageData.relativePath;
  const isEnglish = file.startsWith(ENGLISH_PREFIX);
  const home = HOMES[file];
  if (home !== undefined) {
    pageData.title = home.title;
    pageData.description = home.description;
  } else if (!pageData.description) {
    pageData.description = isEnglish
      ? DEFAULT_DESCRIPTION.en
      : DEFAULT_DESCRIPTION.zh;
  }
  pageData.title = forSearch(pageData.title);
  pageData.description = forSearch(pageData.description);

  const url = pageUrl(file);
  const chineseFile = isEnglish ? file.slice(ENGLISH_PREFIX.length) : file;
  const englishFile = isEnglish ? file : `${ENGLISH_PREFIX}${file}`;
  const hasChinese = existsSync(join(srcDir, chineseFile));
  const hasEnglish = existsSync(join(srcDir, englishFile));
  const languages: HeadConfig[] = [];
  if (hasChinese && hasEnglish) {
    languages.push(
      [
        "link",
        { rel: "alternate", hreflang: "zh-CN", href: pageUrl(chineseFile) },
      ],
      [
        "link",
        { rel: "alternate", hreflang: "en", href: pageUrl(englishFile) },
      ],
      [
        "link",
        { rel: "alternate", hreflang: "x-default", href: pageUrl(chineseFile) },
      ],
    );
  } else {
    languages.push([
      "link",
      { rel: "alternate", hreflang: isEnglish ? "en" : "zh-CN", href: url },
    ]);
  }

  const siteName = isEnglish ? SITE_NAME.en : SITE_NAME.zh;
  const isTitleAlone = pageData.frontmatter.titleTemplate === false;
  const fullTitle = isTitleAlone
    ? pageData.title
    : `${siteName} | ${pageData.title}`;
  const preview: HeadConfig[] = [
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:site_name", content: siteName }],
    ["meta", { property: "og:title", content: fullTitle }],
    ["meta", { property: "og:url", content: url }],
    ["meta", { property: "og:image", content: SOCIAL_IMAGE }],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
    ["meta", { property: "og:description", content: pageData.description }],
  ];

  pageData.frontmatter.head = [
    ...(pageData.frontmatter.head ?? []),
    ["link", { rel: "canonical", href: url }],
    ...languages,
    ...preview,
  ];
}
