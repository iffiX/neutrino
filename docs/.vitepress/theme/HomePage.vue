<script setup lang="ts">
import { computed, ref } from "vue";
import { useData, useRouter, withBase } from "vitepress";
import * as chinese from "./home_content";
import * as english from "./home_content_en";
import { DEMO_URL } from "./home_content";

const { lang } = useData();
const isEnglish = computed(() => lang.value === "en");
// The page's words and lists in its own language; commands, files and pictures are shared.
const page = computed(() => (isEnglish.value ? english : chinese));
const SITES = computed(() => page.value.SITES);
const PARTS = computed(() => page.value.PARTS);
const SYSTEMS = computed(() => page.value.SYSTEMS);
const w = computed(() => page.value.WORDS);
const demoUrl = computed(() =>
  isEnglish.value ? `${DEMO_URL}?lang=en` : DEMO_URL,
);

const pictures = computed(() =>
  Object.fromEntries(
    Object.entries(page.value.PICTURES).map(([key, path]) => [
      key,
      withBase(path),
    ]),
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

const site = ref(isEnglish.value ? chinese.SITES[1].id : chinese.SITES[0].id);
const part = ref(chinese.PARTS[0].id);
const system = ref(chinese.SYSTEMS[0].name);
const copied = ref(false);

const siteInfo = computed(
  () => SITES.value.find((item) => item.id === site.value) ?? SITES.value[0],
);
const systems = computed(() =>
  SYSTEMS.value.filter((item) => part.value === "client" || !item.isPhone),
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
const views = computed(() =>
  PARTS.value.flatMap((item) =>
    SYSTEMS.value
      .filter((entry) => item.id === "client" || !entry.isPhone)
      .flatMap((entry) =>
        SITES.value.map((where) => {
          const packages = entry
            .packages(item.id, where.suffix)
            .map((pack) => ({
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
                  {
                    label: w.value.guide,
                    title: "",
                    href: withBase(entry.guide),
                  },
                ]
              : packages,
          };
        }),
      ),
  ),
);

function choosePart(next: string): void {
  part.value = next;
  system.value = next === "client" ? "Android" : "Linux";
}

function slideSite(): void {
  site.value =
    site.value === SITES.value[0].id ? SITES.value[1].id : SITES.value[0].id;
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
const lines = computed(() =>
  page.value.WAYS_IN.map((name, index) => {
    const y = 62 + index * 76;
    return {
      name,
      d: `M${FROM.x} ${FROM.y} C 590 ${y}, 750 ${y}, ${PHONE.x} ${PHONE.y}`,
      labelY: 0.75 * y + 0.25 * ((FROM.y + PHONE.y) / 2) - 8,
      isFastest: index === 3,
    };
  }),
);
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
          <p class="home-name">{{ w.name }}</p>
          <h1>
            <span v-for="part_ in w.title" :key="part_">{{ part_ }}</span>
          </h1>
          <p class="home-lead">{{ w.lead }}</p>
          <p class="home-small">{{ w.small }}</p>
          <div class="home-actions">
            <a
              class="home-btn is-brand"
              :href="withBase(w.quickStartLink)"
              @click="go(w.quickStartLink, $event)"
              >{{ w.quickStart }}</a
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
            <a
              class="home-btn"
              :href="demoUrl"
              target="_blank"
              rel="noopener"
              >{{ w.demo }}</a
            >
          </div>
          <div class="home-command">
            <div class="home-command-head">
              <div
                class="home-tabs"
                role="tablist"
                :aria-label="w.chooseSystem"
              >
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
                  :aria-label="w.switchSite"
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
                    {{ copied ? w.copied : w.copy }}
                  </button>
                </div>
                <p v-else class="home-command-note">
                  <span class="is-wide">{{ view.caption }}</span>
                  <span class="is-narrow">{{ view.phoneCaption }}</span>
                </p>
                <div class="home-command-link">
                  <span>{{ w.download }}</span>
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
                  :alt="w.qrAlt"
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
              :alt="w.heroPanelAlt"
            />
            <span class="home-frame-base" />
          </div>
          <div class="home-frame is-phone home-hero-phone">
            <img
              class="home-shot"
              :src="pictures.heroPhone"
              :alt="w.heroPhoneAlt"
            />
          </div>
        </div>
      </div>
    </section>

    <section class="home-band">
      <div class="home-wrap home-split">
        <div class="home-copy-col">
          <h2>{{ w.deployTitle }}</h2>
          <p class="home-text">{{ w.deployText }}</p>
          <ul class="home-groups">
            <li v-for="group in page.APP_GROUPS" :key="group.label">
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
          <p class="home-text home-groups-note">{{ w.deployNote }}</p>
        </div>
        <figure class="home-deploy">
          <div class="home-frame">
            <img
              class="home-shot"
              :src="pictures.store"
              :alt="w.storeAlt"
              loading="lazy"
            />
          </div>
          <img
            class="home-wolf home-deploy-wolf"
            :src="pictures.wolfSit"
            :alt="w.wolfSitAlt"
            loading="lazy"
          />
        </figure>
      </div>
    </section>

    <section class="home-band is-grey">
      <div class="home-wrap">
        <div class="home-section-head">
          <h2>{{ w.waysTitle }}</h2>
          <p class="home-text">{{ w.waysText }}</p>
        </div>
        <div class="home-ways-stage">
          <svg
            class="home-ways"
            viewBox="0 0 1200 520"
            role="img"
            :aria-label="w.waysAria"
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
              :alt="w.laptopAlt"
              loading="lazy"
            />
            <span class="home-frame-base" />
          </div>
        </div>
        <p class="home-ways-names">
          {{ page.WAYS_IN.join(w.waysSeparator) }}
        </p>
        <p class="home-ways-note">{{ w.waysNote }}</p>
      </div>
    </section>

    <section class="home-band">
      <div class="home-wrap">
        <div class="home-section-head">
          <h2>{{ w.shareTitle }}</h2>
          <p class="home-text">{{ w.shareText }}</p>
        </div>
        <div class="home-share">
          <figure class="home-share-dialog">
            <div class="home-frame">
              <img
                class="home-shot"
                :src="pictures.shareDialog"
                :alt="w.shareDialogAlt"
                loading="lazy"
              />
            </div>
            <figcaption>{{ w.shareYou }}</figcaption>
          </figure>
          <img
            class="home-wolf home-share-wolves"
            :src="pictures.wolfTwo"
            :alt="w.wolfTwoAlt"
            loading="lazy"
          />
          <figure class="home-share-browser">
            <div class="home-frame">
              <img
                class="home-shot"
                :src="pictures.shareBrowser"
                :alt="w.shareBrowserAlt"
                loading="lazy"
              />
            </div>
            <figcaption>{{ w.shareFriend }}</figcaption>
          </figure>
        </div>
      </div>
    </section>

    <section class="home-band is-grey">
      <div class="home-wrap">
        <div class="home-section-head">
          <h2>{{ w.advancedTitle }}</h2>
        </div>
        <ul class="home-advanced">
          <li v-for="item in page.ADVANCED" :key="item.title">
            <a
              class="home-advanced-card"
              :href="withBase(item.link)"
              @click="go(item.link, $event)"
            >
              <h3>{{ item.title }}</h3>
              <p>
                <code v-if="item.command">{{ item.command }}</code>
                {{ item.text }}
              </p>
            </a>
          </li>
        </ul>
      </div>
    </section>

    <section class="home-band">
      <div class="home-wrap home-three">
        <div v-for="point in w.points" :key="point.title">
          <h3>{{ point.title }}</h3>
          <p>
            <template v-for="(line, index) in point.lines" :key="index">
              <br v-if="index" /><span v-html="line" />
            </template>
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
                  v-for="product in page.COMPARE_PRODUCTS"
                  :key="product"
                  :class="{ 'is-ours': product === page.COMPARE_PRODUCTS[0] }"
                >
                  {{ product }}
                </th>
              </tr>
            </thead>
            <tbody v-for="group in page.COMPARE_GROUPS" :key="group.title">
              <tr class="home-table-group">
                <th :colspan="page.COMPARE_PRODUCTS.length + 1">
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
        <p class="home-table-note">{{ w.tableNote }}</p>
      </div>
    </section>
  </div>
</template>
