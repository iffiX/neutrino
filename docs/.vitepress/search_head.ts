import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { HeadConfig, PageData } from "vitepress";

/**
 * What search engines and link previews read of a page: its search title, a
 * description from its first paragraph, the canonical address, the address of
 * the same page in the other language, and the preview card.
 */

const SITE = "https://neutrinohub.net";
const SOCIAL_IMAGE = `${SITE}/social_preview.png`;
const ENGLISH_PREFIX = "en/";
const CHINESE_LIMIT = 120;
const ENGLISH_LIMIT = 160;
const SITE_NAME = { zh: "微子中枢", en: "Neutrino Hub" };

/** The description of a page that has no first paragraph, and of the site. */
export const DEFAULT_DESCRIPTION = {
  zh: "把要用的软件安装到你自己的电脑上，手机和笔记本随时打开，还能发个链接给同学用。",
  en: "Deploy apps in one click and use them anywhere.",
};

/** The home pages' search title and description, which replace the page's own. */
const HOMES: Record<string, { title: string; description: string }> = {
  "index.md": {
    title: "微子中枢：一键部署面板和智能访问路由",
    description:
      "微子中枢是一键部署面板和智能访问路由。你在自己电脑上一键部署 VS Code、Claude Code、远程桌面等应用，出门用手机和笔记本都能访问，还能发个链接给同学用浏览器打开。",
  },
  "en/index.md": {
    title: "Neutrino Hub: one-click deploy panel and smart access routing",
    description:
      "Neutrino Hub is a one-click deploy panel with smart access routing. Deploy VS Code, Claude Code, remote desktop and more on your own computer, use them from your phone and laptop anywhere, and share a web app with a link that opens in any browser.",
  },
};

/** Search titles that differ from a page's H1, by the page's file; the site name is added after them. */
const SEARCH_TITLES: Record<string, string> = {
  "deploy/claude_code.md": "Claude Code 一键安装，手机远程使用",
  "deploy/codex.md": "Codex 一键安装，手机远程使用",
  "deploy/cloudcli.md": "CloudCLI 一键部署，手机远程使用",
  "deploy/codeg.md": "Codeg 一键部署，手机远程使用",
  "deploy/hermes_webui.md": "Hermes WebUI 一键部署，手机远程使用",
  "deploy/siyuan.md": "思源笔记一键部署，手机远程使用",
  "deploy/code_server.md": "code-server 一键部署，浏览器里远程写代码",
  "deploy/vscode.md": "VS Code 一键安装，远程开发",
  "deploy/remote_desktop.md": "远程桌面一键配置，手机和笔记本连回家里电脑",
  "deploy/file_share.md": "文件共享一键配置，出门访问家里电脑的文件",
  "access/ways_in.md": "从外面访问家里电脑，没有公网 IP 也行：6 种方式",
  "access/sakurafrp.md": "SakuraFrp 远程访问家里电脑",
  "access/openfrp.md": "OpenFrp 远程访问家里电脑",
  "access/easytier.md": "EasyTier 远程访问家里电脑",
  "access/netbird.md": "NetBird 远程访问家里电脑",
  "access/vps.md": "SSH 中继：用 VPS 访问家里电脑",
  "hub/ai_gateway.md": "AI 网关：配一次，每台电脑的 Claude Code、Codex 都能用",
  "hub/agents.md": "多台电脑管理和远程唤醒",
  "share/web_share.md": "分享网页应用：发个链接，对方浏览器直接用",
  "en/deploy/claude_code.md":
    "Install Claude Code in one click and use it from your phone",
  "en/deploy/codex.md": "Install Codex in one click and use it from your phone",
  "en/deploy/cloudcli.md":
    "Deploy CloudCLI in one click and use it from your phone",
  "en/deploy/codeg.md": "Deploy Codeg in one click and use it from your phone",
  "en/deploy/hermes_webui.md":
    "Deploy Hermes WebUI in one click and use it from your phone",
  "en/deploy/siyuan.md":
    "Deploy SiYuan in one click and use it from your phone",
  "en/deploy/code_server.md":
    "Deploy code-server in one click and code remotely in a browser",
  "en/deploy/vscode.md": "Install VS Code in one click for remote development",
  "en/deploy/remote_desktop.md":
    "Set up remote desktop in one click and reach your home computer from your phone and laptop",
  "en/deploy/file_share.md":
    "Set up file sharing in one click and reach your home computer's files from anywhere",
  "en/access/ways_in.md":
    "Reach your home computer from outside, even without a public IP: 6 ways",
  "en/access/sakurafrp.md": "SakuraFrp: reach your home computer remotely",
  "en/access/openfrp.md": "OpenFrp: reach your home computer remotely",
  "en/access/easytier.md": "EasyTier: reach your home computer remotely",
  "en/access/netbird.md": "NetBird: reach your home computer remotely",
  "en/access/vps.md": "SSH relay: reach your home computer through a VPS",
  "en/hub/ai_gateway.md":
    "AI gateway: set it up once, and Claude Code and Codex on every computer can use it",
  "en/hub/agents.md": "Manage several computers and wake them remotely",
  "en/share/web_share.md":
    "Share a web app: send a link that opens in any browser",
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

/** The first paragraph of a page's text, its Markdown and components taken out. */
function firstParagraph(file: string): string {
  const text = readFileSync(file, "utf-8")
    .replace(/^---\n[\s\S]*?\n---\n/, "")
    .replace(/```[\s\S]*?```/g, "");
  for (const block of text.split(/\n\s*\n/)) {
    const lead = block.trim();
    if (!lead || /^(#|<|!\[|\||:::|[-*+] |\d+\. |>)/.test(lead)) {
      continue;
    }
    return lead
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/<[^>]+>/g, "")
      .replace(/(\*\*|__|\*|`)/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }
  return "";
}

/** A description cut at a full stop to the length search engines show. */
function shorten(text: string, isEnglish: boolean): string {
  const limit = isEnglish ? ENGLISH_LIMIT : CHINESE_LIMIT;
  if (text.length <= limit) {
    return text;
  }
  const head = text.slice(0, limit);
  const stop = isEnglish
    ? head.lastIndexOf(". ") + 1
    : head.lastIndexOf("。") + 1;
  return stop > 0 ? head.slice(0, stop).trim() : `${head.slice(0, limit - 1)}…`;
}

/**
 * Sets a page's search title and description, and adds its canonical,
 * language and preview tags to its head.
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
  } else {
    pageData.title = SEARCH_TITLES[file] ?? pageData.title;
    if (!pageData.description) {
      pageData.description =
        shorten(firstParagraph(join(srcDir, file)), isEnglish) ||
        (isEnglish ? DEFAULT_DESCRIPTION.en : DEFAULT_DESCRIPTION.zh);
    }
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
    : `${pageData.title} | ${siteName}`;
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
