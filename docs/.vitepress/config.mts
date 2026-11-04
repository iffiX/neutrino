import { defineConfig, type HeadConfig } from "vitepress";
import { GITHUB_URL, nav, sidebar } from "./navigation.ts";
import { shotsPlugin } from "./shots_plugin.ts";

/** Chinese needs a word segmenter; the default tokenizer splits on spaces. */
function segmentChinese(text: string): string[] {
  const segmenter = new Intl.Segmenter("zh-CN", { granularity: "word" });
  return Array.from(segmenter.segment(text))
    .filter((segment) => segment.isWordLike)
    .map((segment) => segment.segment);
}

// A search result reads the name without the dot the pages show.
const SHOWN_NAME = "微子·中枢";
const SEARCH_NAME = "微子中枢";
const REPOSITORY = "https://github.com/iffiX/neutrino";
const authorLink = (home: string) =>
  `<a href="${home}" rel="author">Muhan Li / iffiX</a>`;

function forSearch(text: string): string {
  return text.replaceAll(SHOWN_NAME, SEARCH_NAME);
}

const draftHead: HeadConfig[] = process.env.NEUTRINO_DRAFT
  ? [["meta", { name: "robots", content: "noindex" }]]
  : [];

export default defineConfig({
  base: process.env.NEUTRINO_DOCS_BASE || "/",
  lang: "zh-CN",
  title: SEARCH_NAME,
  description:
    "把要用的软件安装到你自己的电脑上，手机和笔记本随时打开，还能发个链接给同学用。",
  cleanUrls: true,
  lastUpdated: false,
  srcExclude: ["README.md", "SOURCES.md"],
  sitemap: { hostname: "https://neutrinohub.net" },
  appearance: { initialValue: "dark" },
  head: [
    ...draftHead,
    ["meta", { name: "theme-color", content: "#0e7490" }],
    [
      "link",
      {
        rel: "icon",
        type: "image/png",
        sizes: "16x16",
        href: "/favicon_16.png",
      },
    ],
    [
      "link",
      {
        rel: "icon",
        type: "image/png",
        sizes: "32x32",
        href: "/favicon_32.png",
      },
    ],
  ],
  markdown: {
    config(md) {
      md.use(shotsPlugin);
    },
  },
  vite: {
    server: { fs: { allow: ["..", "../.."] } },
  },
  transformPageData(pageData) {
    pageData.title = forSearch(pageData.title);
    pageData.description = forSearch(pageData.description);
  },
  themeConfig: {
    logo: { src: "/logo.png", alt: "微子·中枢" },
    siteTitle: "微子·中枢",
    nav,
    sidebar,
    socialLinks: [{ icon: "github", link: GITHUB_URL }],
    aside: true,
    outline: { level: [2, 3], label: "本页目录" },
    docFooter: { prev: "上一页", next: "下一页" },
    sidebarMenuLabel: "章节目录",
    returnToTopLabel: "返回顶部",
    darkModeSwitchLabel: "外观",
    lightModeSwitchTitle: "切换为浅色模式",
    darkModeSwitchTitle: "切换为深色模式",
    skipToContentLabel: "跳到正文",
    notFound: {
      code: "404",
      title: "找不到这个页面",
      quote: "可以从首页开始，或者搜索需要的内容。",
      linkLabel: "返回首页",
      linkText: "返回首页",
    },
    search: {
      provider: "local",
      options: {
        miniSearch: { options: { tokenize: segmentChinese } },
        locales: {
          en: {
            translations: {
              button: { buttonText: "Search", buttonAriaLabel: "Search" },
              modal: {
                displayDetails: "Show details",
                resetButtonTitle: "Clear",
                backButtonTitle: "Close",
                noResultsText: "No results",
                footer: {
                  selectText: "Select",
                  navigateText: "Move",
                  closeText: "Close",
                },
              },
            },
          },
        },
        translations: {
          button: { buttonText: "搜索文档", buttonAriaLabel: "搜索文档" },
          modal: {
            displayDetails: "显示详细内容",
            resetButtonTitle: "清空搜索",
            backButtonTitle: "关闭搜索",
            noResultsText: "没有找到相关文档",
            footer: {
              selectText: "选择",
              navigateText: "切换",
              closeText: "关闭",
            },
          },
        },
      },
    },
    i18nRouting: false,
    langMenuLabel: "切换语言",
    footer: {
      message:
        `微子使用 <a href="${REPOSITORY}/blob/main/LICENSE">MIT</a> 与 ` +
        `<a href="${REPOSITORY}/blob/main/client/android/LICENSE">AGPL-3.0</a> 许可证分发`,
      copyright: `© 2026 作者 ${authorLink("https://www.beyond-infinity.top/zh/")}`,
    },
  },
  locales: {
    root: { label: "简体中文", lang: "zh-CN" },
    en: {
      label: "English",
      lang: "en",
      link: "/en/",
      title: "Neutrino Hub",
      description: "Deploy apps in one click and use them anywhere.",
      themeConfig: {
        logo: { src: "/logo.png", alt: "Neutrino Hub" },
        siteTitle: "Neutrino Hub",
        nav: [],
        sidebar: [],
        langMenuLabel: "Change language",
        darkModeSwitchLabel: "Appearance",
        lightModeSwitchTitle: "Switch to light mode",
        darkModeSwitchTitle: "Switch to dark mode",
        skipToContentLabel: "Skip to content",
        footer: {
          message:
            `Neutrino is distributed under the <a href="${REPOSITORY}/blob/main/LICENSE">MIT</a> and ` +
            `<a href="${REPOSITORY}/blob/main/client/android/LICENSE">AGPL-3.0</a> licenses`,
          copyright: `© 2026 Author ${authorLink("https://www.beyond-infinity.top/")}`,
        },
      },
    },
  },
});
