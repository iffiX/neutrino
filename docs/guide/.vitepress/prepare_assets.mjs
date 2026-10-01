import {
  access,
  copyFile,
  cp,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from "node:fs/promises";
import { Buffer } from "node:buffer";
import { URL, fileURLToPath } from "node:url";
import sharp from "sharp";

const publicDirectory = new URL("../public/", import.meta.url);
const iconDirectory = new URL("../../../images/icons/", import.meta.url);
const guideSource = new URL("../../../images/guide/", import.meta.url);
const guideTarget = new URL("guide/", publicDirectory);
const webDirectory = new URL("../../../images/web/", import.meta.url);
const shotTable = new URL(
  "../../../packaging/screenshots/shots.json",
  import.meta.url,
);

// A 1x1 transparent webp, standing in for a screenshot not captured yet.
const PLACEHOLDER_WEBP = Buffer.from(
  "UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==",
  "base64",
);
const WEBP_QUALITY = 90;

await mkdir(publicDirectory, { recursive: true });

for (const name of ["neutrino_64.png", "neutrino_512.png"]) {
  await copyFile(new URL(name, iconDirectory), new URL(name, publicDirectory));
}

await mkdir(guideTarget, { recursive: true });

if (await exists(guideSource)) {
  await cp(guideSource, guideTarget, { recursive: true });
  await convertCaptures(guideSource, guideTarget);
}

await fillMissingShots();

for (const name of ["architecture.svg", "architecture_zh.svg"]) {
  const source = new URL(name, webDirectory);
  if (await exists(source)) {
    await copyFile(source, new URL(name, guideTarget));
  }
}

/**
 * Write each captured png as the webp the pages reference.
 *
 * A capture replaces an older webp of the same name.
 *
 * @param {URL} source The images/guide directory.
 * @param {URL} target Its copy under public/.
 * @returns {Promise<void>}
 */
async function convertCaptures(source, target) {
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const directory = `${entry.name}/`;
      await mkdir(new URL(directory, target), { recursive: true });
      await convertCaptures(
        new URL(directory, source),
        new URL(directory, target),
      );
    } else if (entry.name.endsWith(".png")) {
      const webpName = entry.name.replace(/\.png$/, ".webp");
      await sharp(fileURLToPath(new URL(entry.name, source)))
        .webp({ quality: WEBP_QUALITY })
        .toFile(fileURLToPath(new URL(webpName, target)));
    }
  }
}

/**
 * Put a placeholder where the shot table names an image not captured yet.
 *
 * The images are captured on a live hub after the pages are written, so a
 * missing one is a warning and the build goes on.
 *
 * @returns {Promise<void>}
 */
async function fillMissingShots() {
  if (!(await exists(shotTable))) {
    return;
  }
  const table = JSON.parse(await readFile(shotTable, "utf8"));
  const missing = [];
  for (const shot of table.shots) {
    const webpName = shot.file.replace(/\.png$/, ".webp");
    const target = new URL(`${shot.language}/${webpName}`, guideTarget);
    if (!(await exists(target))) {
      await mkdir(new URL(`${shot.language}/`, guideTarget), {
        recursive: true,
      });
      await writeFile(target, PLACEHOLDER_WEBP);
      missing.push(`${shot.language}/${shot.file}`);
    }
  }
  if (missing.length > 0) {
    process.stderr.write(
      `prepare_assets: ${missing.length} screenshots not captured yet, placeholders written: ${missing.join(", ")}\n`,
    );
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
