// The client page's bridge in the demo, in place of the desktop window's
// pywebview. It loads before app.js and replies once every script of the page
// has run. The replies come from the top window's fake client core, so a frame
// opened alone goes there.
(function () {
  if (window.parent === window) {
    window.location.replace("../");
    return;
  }
  const core = window.parent.neutrinoDemoClient;
  const pageReady = new Promise((resolve) =>
    document.addEventListener("DOMContentLoaded", resolve),
  );

  window.pywebview = {
    api: {
      request(request) {
        return pageReady.then(() => ({
          body: JSON.parse(JSON.stringify(core.request(request))),
        }));
      },
    },
  };

  core.onState((state) => {
    if (window.neutrinoState) {
      window.neutrinoState(JSON.parse(JSON.stringify(state)));
    }
  });
})();
