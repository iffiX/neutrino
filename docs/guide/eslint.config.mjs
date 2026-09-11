import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      ".vitepress/dist/**",
      ".vitepress/cache/**",
      ".vitepress/.temp/**",
      "node_modules/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { process: "readonly" } } },
);
