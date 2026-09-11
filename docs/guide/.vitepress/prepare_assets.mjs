import { access, copyFile, cp, mkdir } from "node:fs/promises";
import { URL } from "node:url";

const publicDirectory = new URL("../public/", import.meta.url);
const iconDirectory = new URL("../../../images/icons/", import.meta.url);
const guideSource = new URL("../../../images/guide/", import.meta.url);
const guideTarget = new URL("guide/", publicDirectory);
const webDirectory = new URL("../../../images/web/", import.meta.url);

await mkdir(publicDirectory, { recursive: true });

for (const name of ["neutrino_64.png", "neutrino_512.png"]) {
  await copyFile(new URL(name, iconDirectory), new URL(name, publicDirectory));
}

await mkdir(guideTarget, { recursive: true });

// The screenshots are taken and reviewed outside the build, so a working copy
// without them still builds; the pages show broken images and nothing else.
if (await exists(guideSource)) {
  await cp(guideSource, guideTarget, { recursive: true });
}

for (const name of ["architecture.svg", "architecture_zh.svg"]) {
  const source = new URL(name, webDirectory);
  if (await exists(source)) {
    await copyFile(source, new URL(name, guideTarget));
  }
}

/**
 * Whether a path is there to be copied.
 *
 * @param {URL} url The path to test.
 * @returns {Promise<boolean>} True when it can be read.
 */
async function exists(url) {
  try {
    await access(url);
    return true;
  } catch {
    return false;
  }
}
