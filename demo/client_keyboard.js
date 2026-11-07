// The phone's keyboard in the demo: a page has no way to show a system keyboard
// inside the phone's frame, so it draws one. A press hands its bytes over as a
// terminal takes them.
const phoneKeyboard = (() => {
  const PAGES = [
    ["qwertyuiop", "asdfghjkl", "zxcvbnm"],
    ["1234567890", '-/:;()$&@"', ".,?!'"],
    ["[]{}#%^*+=", "_\\|~<>", ".,?!'"],
  ];
  const ENTER = "\r";
  const BACKSPACE = "\x7f";

  let element = null;
  let onType = null;
  let page = 0;
  let isUpper = false;

  function key(label, className, press) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kb_key " + className;
    button.textContent = label;
    button.onmousedown = (event) => event.preventDefault();
    button.onclick = press;
    return button;
  }

  function type(text) {
    if (onType) onType(text);
    if (isUpper && page === 0) {
      isUpper = false;
      draw();
    }
  }

  function row(keys, className) {
    const line = document.createElement("div");
    line.className = "kb_row " + (className || "");
    for (const each of keys) line.appendChild(each);
    return line;
  }

  function letterKeys(letters) {
    return Array.from(letters).map((letter) => {
      const shown = isUpper && page === 0 ? letter.toUpperCase() : letter;
      return key(shown, "", () => type(shown));
    });
  }

  function draw() {
    element.replaceChildren();
    const [first, second, third] = PAGES[page];
    element.appendChild(row(letterKeys(first)));
    element.appendChild(row(letterKeys(second)));
    const shift =
      page === 0
        ? key("⇧", "kb_wide" + (isUpper ? " on" : ""), () => {
            isUpper = !isUpper;
            draw();
          })
        : key(page === 1 ? "#+=" : "123", "kb_wide", () => {
            page = page === 1 ? 2 : 1;
            draw();
          });
    element.appendChild(
      row([
        shift,
        ...letterKeys(third),
        key("⌫", "kb_wide", () => type(BACKSPACE)),
      ]),
    );
    element.appendChild(
      row([
        key(page === 0 ? "123" : "ABC", "kb_wide", () => {
          page = page === 0 ? 1 : 0;
          draw();
        }),
        key("-", "", () => type("-")),
        key("/", "", () => type("/")),
        key(" ", "kb_space", () => type(" ")),
        key(".", "", () => type(".")),
        key("⏎", "kb_wide kb_enter", () => type(ENTER)),
      ]),
    );
  }

  return {
    show(host, handler) {
      if (!element) {
        element = document.createElement("div");
        element.className = "kb";
      }
      onType = handler;
      page = 0;
      isUpper = false;
      draw();
      host.appendChild(element);
      element.classList.toggle("kb_low", host.clientHeight < host.clientWidth);
    },
    hide() {
      if (element) element.remove();
      onType = null;
    },
    isShown() {
      return !!element && element.isConnected;
    },
    height() {
      return this.isShown() ? element.offsetHeight : 0;
    },
  };
})();
