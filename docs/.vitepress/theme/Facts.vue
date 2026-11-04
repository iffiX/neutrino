<script setup lang="ts">
import { computed } from "vue";
import { useData } from "vitepress";

const props = defineProps<{
  systems?: string;
  editions?: string;
  since?: string;
}>();
const { lang } = useData();

const ALL_SYSTEMS = ["Linux", "Windows", "macOS"];
const ALL_EDITIONS = ["国际版", "国内版"];
const EDITION_WORDS: Record<string, string> = {
  国际版: "International",
  国内版: "China",
};

const isEnglish = computed(() => lang.value === "en");
const labels = computed(() =>
  isEnglish.value
    ? { systems: "Systems", editions: "Editions", since: "Since" }
    : { systems: "支持的系统", editions: "支持的版本", since: "开始支持" },
);
const split = (text?: string) =>
  (text ?? "")
    .split(",")
    .map((word) => word.trim())
    .filter(Boolean);
const shown = (word: string) =>
  isEnglish.value ? (EDITION_WORDS[word] ?? word) : word;
</script>

<template>
  <div class="doc-facts">
    <div v-if="systems" class="doc-facts-cell">
      <span class="doc-facts-label">{{ labels.systems }}</span>
      <span class="doc-facts-chips">
        <span
          v-for="system in ALL_SYSTEMS"
          :key="system"
          class="doc-chip"
          :class="split(systems).includes(system) ? 'is-on' : 'is-off'"
          >{{ system }}</span
        >
      </span>
    </div>
    <div v-if="editions" class="doc-facts-cell">
      <span class="doc-facts-label">{{ labels.editions }}</span>
      <span class="doc-facts-chips">
        <span
          v-for="edition in ALL_EDITIONS"
          :key="edition"
          class="doc-chip"
          :class="split(editions).includes(edition) ? 'is-on' : 'is-off'"
          >{{ shown(edition) }}</span
        >
      </span>
    </div>
    <div v-if="since" class="doc-facts-cell">
      <span class="doc-facts-label">{{ labels.since }}</span>
      <span class="doc-facts-chips"
        ><span class="doc-chip is-since">v{{ since }}</span></span
      >
    </div>
  </div>
</template>
