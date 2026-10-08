import DefaultTheme from "vitepress/theme";
import type { Theme } from "vitepress";
import { HomeGroups } from "./home_groups.ts";
import "./custom.css";

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component("HomeGroups", HomeGroups);
  },
} satisfies Theme;
