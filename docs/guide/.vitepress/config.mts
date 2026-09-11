import { defineConfig } from "vitepress";
import {
  GITHUB_URL,
  navEn,
  navZh,
  sidebarEn,
  sidebarZh,
} from "./navigation.ts";

const basePath = process.env.NEUTRINO_DOCS_BASE || "/";
const base = `${basePath.replace(/\/$/, "")}/`;

if (!base.startsWith("/") || /[?#\s]/.test(base)) {
  throw new Error(
    "NEUTRINO_DOCS_BASE must be an absolute URL path, e.g. /neutrino/.",
  );
}

/** Chinese needs a word segmenter; the default tokenizer splits on spaces. */
function segmentChinese(text: string): string[] {
  const segmenter = new Intl.Segmenter("zh-CN", { granularity: "word" });
  return Array.from(segmenter.segment(text))
    .filter((segment) => segment.isWordLike)
    .map((segment) => segment.segment);
}

export default defineConfig({
  lang: "en-US",
  title: "Neutrino",
  description:
    "Neutrino documentation: install the hub, add machines, publish services.",
  base,
  cleanUrls: false,
  lastUpdated: false,
  srcExclude: ["README.md"],
  head: [["meta", { name: "theme-color", content: "#0891b2" }]],
  locales: {
    root: {
      label: "English",
      lang: "en-US",
      themeConfig: {
        nav: navEn,
        sidebar: sidebarEn,
        outline: { level: [2, 3], label: "On this page" },
        editLink: {
          pattern: `${GITHUB_URL}/edit/main/docs/guide/:path`,
          text: "Edit this page on GitHub",
        },
      },
    },
    "zh-CN": {
      label: "简体中文",
      lang: "zh-CN",
      link: "/zh-CN/",
      description: "Neutrino 使用文档：安装中枢、接入机器、发布服务。",
      themeConfig: {
        nav: navZh,
        sidebar: sidebarZh,
        outline: { level: [2, 3], label: "本页目录" },
        docFooter: { prev: "上一页", next: "下一页" },
        sidebarMenuLabel: "章节目录",
        returnToTopLabel: "返回顶部",
        darkModeSwitchLabel: "外观",
        lightModeSwitchTitle: "切换为浅色模式",
        darkModeSwitchTitle: "切换为深色模式",
        skipToContentLabel: "跳到正文",
        langMenuLabel: "切换语言",
        notFound: {
          code: "404",
          title: "找不到这个页面",
          quote: "可以从首页开始，或者搜索需要的内容。",
          linkLabel: "返回首页",
          linkText: "返回首页",
        },
        editLink: {
          pattern: `${GITHUB_URL}/edit/main/docs/guide/:path`,
          text: "在 GitHub 上编辑此页",
        },
        footer: {
          message: "Neutrino · 个人开发基础设施",
          copyright: "使用 MIT 许可证发布",
        },
      },
    },
  },
  themeConfig: {
    logo: { src: "/neutrino_64.png", alt: "Neutrino" },
    siteTitle: "Neutrino",
    socialLinks: [{ icon: "github", link: GITHUB_URL }],
    search: {
      provider: "local",
      options: {
        miniSearch: {
          options: { tokenize: segmentChinese },
        },
        locales: {
          "zh-CN": {
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
      },
    },
    footer: {
      message: "Neutrino · personal developer infrastructure",
      copyright: "Released under the MIT license",
    },
  },
});
