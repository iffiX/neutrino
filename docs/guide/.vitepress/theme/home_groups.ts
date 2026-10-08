import { defineComponent, h, type PropType } from "vue";
import { VPFeatures } from "vitepress/theme";

/** One card of a group on the home page. */
export interface HomeGroupItem {
  title: string;
  details: string;
  link: string;
}

/**
 * A titled group of cards on the home page.
 *
 * The home page's frontmatter holds each group's cards, and the page body
 * places one `<HomeGroups>` per group, so both languages share one layout.
 * The cards are the default theme's feature cards.
 */
export const HomeGroups = defineComponent({
  name: "HomeGroups",
  props: {
    title: { type: String, required: true },
    items: { type: Array as PropType<HomeGroupItem[]>, required: true },
  },
  setup(props) {
    return () =>
      h("section", { class: "home-group" }, [
        h("div", { class: "home-group-head" }, [
          h("h2", { class: "home-group-title" }, props.title),
        ]),
        h(VPFeatures, { features: props.items }),
      ]);
  },
});
