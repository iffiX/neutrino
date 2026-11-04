<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { withBase } from "vitepress";
import { SITES, VERSION } from "./home_content";

const place = ref("other");
const site = ref(SITES[0]);
const copied = ref(false);

const file = computed(
  () =>
    `${site.value.files}neutrino-client-${VERSION}-android${site.value.suffix}.apk`,
);

onMounted(() => {
  const agent = navigator.userAgent;
  if (/MicroMessenger/i.test(agent)) {
    place.value = "wechat";
  } else if (/iPhone|iPad/i.test(agent)) {
    place.value = "iphone";
  } else if (/Android/i.test(agent)) {
    place.value = "android";
  }
  const wanted = new URLSearchParams(window.location.search).get("site");
  site.value = SITES.find((item) => item.id === wanted) ?? SITES[0];
});

async function copy(): Promise<void> {
  await navigator.clipboard.writeText(window.location.href);
  copied.value = true;
}
</script>

<template>
  <div class="app-page">
    <template v-if="place === 'wechat'">
      <p class="app-arrow" aria-hidden="true">↗</p>
      <h1>换浏览器打开下载</h1>
      <ol>
        <li>点右上角的 <b>···</b></li>
        <li>选 <b>在浏览器打开</b></li>
        <li>在浏览器里点 <b>下载</b></li>
      </ol>
      <button class="app-button is-plain" type="button" @click="copy">
        {{ copied ? "已复制，粘到浏览器" : "复制这个网址" }}
      </button>
    </template>
    <template v-else-if="place === 'iphone'">
      <h1>iPhone 要自己签名安装</h1>
      <a class="app-button" :href="withBase('/access/ios')">查看安装方法</a>
    </template>
    <template v-else>
      <h1>微子·中枢安卓客户端</h1>
      <p class="app-note">{{ site.label }} {{ VERSION }}</p>
      <a class="app-button" :href="file">下载</a>
      <p class="app-note">下载后打开文件。手机提示时，允许安装。</p>
    </template>
  </div>
</template>

<style scoped>
.app-page {
  position: relative;
  max-width: 420px;
  margin: 0 auto;
  padding: 72px 24px;
  text-align: center;
}

.app-page h1 {
  margin: 0 0 20px;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.35;
}

.app-page ol {
  margin: 0 0 28px;
  padding: 0;
  list-style-position: inside;
  font-size: 18px;
  line-height: 2;
}

.app-arrow {
  position: fixed;
  top: 8px;
  right: 18px;
  margin: 0;
  color: var(--vp-c-brand-1);
  font-size: 56px;
  line-height: 1;
}

.app-button {
  display: block;
  padding: 14px;
  border: 1px solid var(--vp-c-brand-1);
  border-radius: 10px;
  background: var(--vp-c-brand-1);
  color: var(--vp-c-bg);
  font-size: 18px;
  font-weight: 700;
  text-decoration: none;
}

.app-button.is-plain {
  width: 100%;
  background: none;
  color: var(--vp-c-brand-1);
}

.app-note {
  margin: 16px 0;
  color: var(--vp-c-text-2);
  font-size: 15px;
}
</style>
