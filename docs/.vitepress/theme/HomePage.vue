<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter, withBase } from "vitepress";
import {
  APP_GROUPS,
  COMPARE_GROUPS,
  COMPARE_PRODUCTS,
  DEMO_URL,
  PARTS,
  PICTURES,
  SITES,
  SYSTEMS,
  WAYS_IN,
} from "./home_content";

const pictures = computed(() =>
  Object.fromEntries(
    Object.entries(PICTURES).map(([key, path]) => [key, withBase(path)]),
  ),
);
const router = useRouter();

function iconStyle(icon: string): Record<string, string> {
  const url = `url(${withBase(`/home/icons/${icon}.svg`)})`;
  return { "-webkit-mask-image": url, "mask-image": url };
}

function go(link: string, event: Event): void {
  event.preventDefault();
  void router.go(withBase(link));
}

const site = ref(SITES[0].id);
const part = ref(PARTS[0].id);
const system = ref(SYSTEMS[0].name);
const copied = ref(false);

const siteInfo = computed(
  () => SITES.find((item) => item.id === site.value) ?? SITES[0],
);
const systems = computed(() =>
  SYSTEMS.filter((item) => part.value === "client" || !item.isPhone),
);
const chosen = computed(
  () =>
    systems.value.find((item) => item.name === system.value) ??
    systems.value[0],
);
const viewKey = computed(
  () => `${part.value}/${chosen.value.name}/${site.value}`,
);

// Every state of the install box; they share one grid cell, so the box keeps the tallest one's height.
const views = PARTS.flatMap((item) =>
  SYSTEMS.filter((entry) => item.id === "client" || !entry.isPhone).flatMap(
    (entry) =>
      SITES.map((where) => {
        const packages = entry.packages(item.id, where.suffix).map((pack) => ({
          label: pack.label,
          title: pack.file,
          href: `${where.files}${pack.file}`,
        }));
        return {
          key: `${item.id}/${entry.name}/${where.id}`,
          command: entry.command?.(where.scripts, item.id) ?? "",
          caption: entry.caption ?? "",
          phoneCaption: entry.phoneCaption ?? entry.caption ?? "",
          qr: entry.hasQr ? withBase(`/home/qr_app_${where.id}.svg`) : "",
          links: entry.guide
            ? [
                ...packages,
                { label: "安装说明", title: "", href: withBase(entry.guide) },
              ]
            : packages,
        };
      }),
  ),
);

function choosePart(next: string): void {
  part.value = next;
  system.value = next === "client" ? "Android" : "Linux";
}

function slideSite(): void {
  site.value = site.value === SITES[0].id ? SITES[1].id : SITES[0].id;
}

async function copy(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1500);
}

// The six ways in: from the computer's edge, fanning out, into the phone in the wolf's paw.
const FROM = { x: 500, y: 268 };
const PHONE = { x: 911, y: 235 };
const lines = WAYS_IN.map((name, index) => {
  const y = 62 + index * 76;
  return {
    name,
    d: `M${FROM.x} ${FROM.y} C 590 ${y}, 750 ${y}, ${PHONE.x} ${PHONE.y}`,
    labelY: 0.75 * y + 0.25 * ((FROM.y + PHONE.y) / 2) - 8,
    isFastest: index === 3,
  };
});
</script>

<template>
  <div class="home">
    <section class="home-hero">
      <div class="home-glow" aria-hidden="true">
        <i class="home-glow-arc is-wide" />
        <i class="home-glow-arc is-mid" />
        <i class="home-glow-arc is-core" />
        <i class="home-glow-arc is-hot" />
        <i class="home-glow-arc is-thin" />
        <i class="home-glow-arc is-corner" />
      </div>

      <div class="home-wrap home-hero-grid">
        <div class="home-hero-text">
          <p class="home-name">微子·中枢</p>
          <h1><span>一键部署应用，</span><span>走到哪用到哪</span></h1>
          <p class="home-lead">
            写代码、写论文、记笔记、远程桌面、传文件。点一下安装到自己电脑上，手机和笔记本随时打开，还能发链接给同学用。
          </p>
          <p class="home-small">
            Windows、macOS、Linux 都能安装。开源，免费，MIT 许可证。
          </p>
          <div class="home-actions">
            <a
              class="home-btn is-brand"
              :href="withBase('/quick-start')"
              @click="go('/quick-start', $event)"
              >快速上手</a
            >
            <button
              v-for="item in PARTS"
              :key="item.id"
              class="home-btn"
              :class="{ 'is-on': part === item.id }"
              type="button"
              :aria-pressed="part === item.id"
              @click="choosePart(item.id)"
            >
              {{ item.label }}
            </button>
            <a class="home-btn" :href="DEMO_URL" target="_blank" rel="noopener"
              >在线演示</a
            >
          </div>
          <div class="home-command">
            <div class="home-command-head">
              <div class="home-tabs" role="tablist" aria-label="选择系统">
                <button
                  v-for="item in SYSTEMS"
                  :key="item.name"
                  role="tab"
                  type="button"
                  :aria-selected="chosen.name === item.name"
                  :class="{
                    'is-on': chosen.name === item.name,
                    'is-hidden': !systems.includes(item),
                  }"
                  @click="system = item.name"
                >
                  {{ item.name }}
                </button>
              </div>
              <div class="home-command-site">
                <span
                  class="home-chip"
                  :class="{ 'is-hidden': !siteInfo.chip }"
                  >{{ SITES[0].chip }}</span
                >
                <button
                  class="home-slide"
                  :class="{ 'is-second': site === SITES[1].id }"
                  role="switch"
                  type="button"
                  :aria-checked="site === SITES[1].id"
                  aria-label="切换国内版和国际版"
                  @click="slideSite"
                >
                  <span class="home-slide-thumb" />
                  <span
                    v-for="item in SITES"
                    :key="item.id"
                    class="home-slide-label"
                    :class="{ 'is-on': site === item.id }"
                    >{{ item.label }}</span
                  >
                </button>
              </div>
            </div>
            <div class="home-command-views">
              <div
                v-for="view in views"
                :key="view.key"
                class="home-command-view"
                :class="{ 'is-on': view.key === viewKey, 'has-qr': view.qr }"
              >
                <div v-if="view.command" class="home-command-line">
                  <code>{{ view.command }}</code>
                  <button
                    class="home-copy"
                    type="button"
                    @click="copy(view.command)"
                  >
                    {{ copied ? "已复制" : "复制" }}
                  </button>
                </div>
                <p v-else class="home-command-note">
                  <span class="is-wide">{{ view.caption }}</span>
                  <span class="is-narrow">{{ view.phoneCaption }}</span>
                </p>
                <div class="home-command-link">
                  <span>下载</span>
                  <a
                    v-for="link in view.links"
                    :key="link.href"
                    :href="link.href"
                    :title="link.title"
                    >{{ link.label }}</a
                  >
                </div>
                <img
                  v-if="view.qr"
                  class="home-command-qr"
                  :src="view.qr"
                  alt="安卓客户端的下载二维码"
                  width="120"
                  height="120"
                />
              </div>
            </div>
          </div>
        </div>
        <div class="home-hero-media">
          <div class="home-frame is-laptop">
            <img
              class="home-shot"
              :src="pictures.heroPanel"
              alt="面板的总览页"
            />
            <span class="home-frame-base" />
          </div>
          <div class="home-frame is-phone home-hero-phone">
            <img
              class="home-shot"
              :src="pictures.heroPhone"
              alt="手机上的应用列表"
            />
          </div>
        </div>
      </div>
    </section>

    <section class="home-band">
      <div class="home-wrap home-split">
        <div class="home-copy-col">
          <h2>一键部署</h2>
          <p class="home-text">
            想用什么，点一下就能安装。不用配环境，不用换系统。容器也一样，Windows、macOS、Linux
            同样的办法部署。多个下载源自动选最快的，安装又稳又快。
          </p>
          <ul class="home-groups">
            <li v-for="group in APP_GROUPS" :key="group.label">
              <span class="home-group-label">{{ group.label }}</span>
              <span class="home-group-apps">
                <a
                  v-for="app in group.apps"
                  :key="app.name"
                  class="home-app"
                  :href="withBase(app.link)"
                  @click="go(app.link, $event)"
                >
                  <i class="home-app-icon" :style="iconStyle(app.icon)" />{{
                    app.name
                  }}
                </a>
              </span>
            </li>
          </ul>
          <p class="home-text home-groups-note">
            列表里没有的也能用：你可以自己声明服务，填多个端口和 HTTP
            入口。容器暴露的端口会自动添加为应用，全部自动。
          </p>
        </div>
        <figure class="home-deploy">
          <div class="home-frame">
            <img
              class="home-shot"
              :src="pictures.store"
              alt="面板上选择要安装的应用"
              loading="lazy"
            />
          </div>
          <img
            class="home-wolf home-deploy-wolf"
            :src="pictures.wolfSit"
            alt="小狼坐在方块上用电脑"
            loading="lazy"
          />
        </figure>
      </div>
    </section>

    <section class="home-band is-grey">
      <div class="home-wrap">
        <div class="home-section-head">
          <h2>到处使用</h2>
          <p class="home-text">
            手机扫一次码，地铁、高铁、飞机 Wi-Fi、国外都能用电脑上的软件。6
            种连接方式，智能路由自动使用最快的一条*。
          </p>
        </div>
        <div class="home-ways-stage">
          <svg
            class="home-ways"
            viewBox="0 0 1200 520"
            role="img"
            aria-label="电脑和手机之间有六种连接方式，走最快的一条"
          >
            <defs>
              <linearGradient id="ways-neon" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stop-color="#08adfe" />
                <stop offset="0.55" stop-color="#8d61f6" />
                <stop offset="1" stop-color="#ef2eb6" />
              </linearGradient>
            </defs>
            <image
              :href="pictures.wolfWalk"
              x="770"
              y="0"
              width="430"
              height="520"
              preserveAspectRatio="xMidYMid meet"
            />
            <g fill="none" stroke="url(#ways-neon)" stroke-linecap="round">
              <path
                v-for="line in lines"
                :key="line.name"
                class="home-way"
                :class="{ 'is-fastest': line.isFastest }"
                :d="line.d"
              />
            </g>
            <text
              v-for="line in lines"
              :key="line.name + '-label'"
              class="home-way-label"
              :class="{ 'is-fastest': line.isFastest }"
              x="679"
              :y="line.labelY"
              text-anchor="middle"
            >
              {{ line.name }}
            </text>
          </svg>
          <div class="home-frame is-laptop home-ways-laptop">
            <img
              class="home-shot"
              :src="pictures.laptop"
              alt="笔记本上的 VS Code"
              loading="lazy"
            />
            <span class="home-frame-base" />
          </div>
        </div>
        <p class="home-ways-names">{{ WAYS_IN.join("、") }}</p>
        <p class="home-ways-note">
          * NetBird 和 EasyTier 要手动选择，其余的自动。iOS
          不包含这两种，你要用美区账号安装它们的 App。
        </p>
      </div>
    </section>

    <section class="home-band">
      <div class="home-wrap">
        <div class="home-section-head">
          <h2>任意分享</h2>
          <p class="home-text">
            任何网页应用，点“分享”得到一个链接。同学用浏览器打开就能用，什么都不用安装。到期失效，也能随时收回。
          </p>
        </div>
        <div class="home-share">
          <figure class="home-share-dialog">
            <div class="home-frame">
              <img
                class="home-shot"
                :src="pictures.shareDialog"
                alt="面板上的分享弹窗"
                loading="lazy"
              />
            </div>
            <figcaption>你点分享</figcaption>
          </figure>
          <img
            class="home-wolf home-share-wolves"
            :src="pictures.wolfTwo"
            alt="两只小狼一起坐在桌边"
            loading="lazy"
          />
          <figure class="home-share-browser">
            <div class="home-frame">
              <img
                class="home-shot"
                :src="pictures.shareBrowser"
                alt="同学的浏览器里打开的 Ayakaleaf"
                loading="lazy"
              />
            </div>
            <figcaption>同学打开</figcaption>
          </figure>
        </div>
      </div>
    </section>

    <section class="home-band is-grey">
      <div class="home-wrap home-three">
        <div>
          <h3>全能</h3>
          <p>
            应用、桌面、终端、文件、SSH。<br />点一下就能安装，客户端里都配好了。
          </p>
        </div>
        <div>
          <h3>安全</h3>
          <p>
            设备和中枢之间全程加密，第三方线路看不到内容。所有应用都受微子<span
              class="home-nowrap"
              >服务端口</span
            >严格保护。<br />只有你许可的人才能访问。
          </p>
        </div>
        <div>
          <h3>自主</h3>
          <p>
            不用买服务器、域名和专用设备。<br />微子不提供公开服务器，<br />分享也只连你的中枢。
          </p>
        </div>
        <div>
          <h3>免费</h3>
          <p>
            管理多台电脑，局域网唤醒，<br />全球连接，不限用户数，<br />不限流量。全部免费。
          </p>
        </div>
      </div>
      <div class="home-wrap">
        <div class="home-table-wrap">
          <table class="home-table">
            <thead>
              <tr>
                <th />
                <th
                  v-for="product in COMPARE_PRODUCTS"
                  :key="product"
                  :class="{ 'is-ours': product === COMPARE_PRODUCTS[0] }"
                >
                  {{ product }}
                </th>
              </tr>
            </thead>
            <tbody v-for="group in COMPARE_GROUPS" :key="group.title">
              <tr class="home-table-group">
                <th :colspan="COMPARE_PRODUCTS.length + 1">
                  {{ group.title }}
                </th>
              </tr>
              <tr v-for="row in group.rows" :key="row[0]">
                <th scope="row">{{ row[0] }}</th>
                <td
                  v-for="(cell, index) in row.slice(1)"
                  :key="index"
                  :class="[
                    cell.startsWith('x:') ? 'is-miss' : 'is-hit',
                    { 'is-ours': index === 0 },
                  ]"
                >
                  {{ cell.replace("x:", "") }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="home-table-note">
          价格和限制来自 2026-10-30
          各家页面。第三方服务以它们的带宽和账号规定为准。
        </p>
      </div>
    </section>
  </div>
</template>
