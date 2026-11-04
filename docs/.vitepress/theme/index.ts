import DefaultTheme from "vitepress/theme";
import type { Theme } from "vitepress";
import AppDownload from "./AppDownload.vue";
import Facts from "./Facts.vue";
import HomePage from "./HomePage.vue";
import "photoswipe/style.css";
import "./custom.css";
import "./home.css";

/** Opens a picture large on a click; arrow keys, swipes and a pinch walk the page's pictures. */
function openPicturesOnClick(): void {
  document.addEventListener("click", async (event) => {
    const picture = (event.target as HTMLElement).closest?.(
      ".shots img, td img",
    );
    if (!picture) {
      return;
    }
    const pictures = [
      ...document.querySelectorAll<HTMLImageElement>(
        ".shots img, .vp-doc td img",
      ),
    ];
    const { default: PhotoSwipe } = await import("photoswipe");
    const viewer = new PhotoSwipe({
      dataSource: pictures.map((shot) => ({
        src: shot.src,
        width: Number(shot.getAttribute("width")) || shot.naturalWidth,
        height: Number(shot.getAttribute("height")) || shot.naturalHeight,
        alt: shot.alt,
      })),
      index: pictures.indexOf(picture as HTMLImageElement),
      bgOpacity: 0.92,
      showHideAnimationType: "fade",
      wheelToZoom: true,
    });
    viewer.on("uiRegister", () => {
      viewer.ui?.registerElement({
        name: "doc-caption",
        order: 9,
        isButton: false,
        appendTo: "root",
        onInit: (element) => {
          viewer.on("change", () => {
            element.textContent = (viewer.currSlide?.data.alt as string) ?? "";
          });
        },
      });
    });
    viewer.init();
  });
}

const theme: Theme = {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component("HomePage", HomePage);
    app.component("AppDownload", AppDownload);
    app.component("Facts", Facts);
    if (typeof document !== "undefined") {
      openPicturesOnClick();
    }
  },
};

export default theme;
