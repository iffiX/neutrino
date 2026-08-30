import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";

import "./fonts.css";
import "./theme.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root container");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
