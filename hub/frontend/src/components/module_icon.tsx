import "./module_icon.css";

/**
 * One module's glyph, drawn after the software's own mark.
 *
 * The files are `images/icons/modules/<module>.svg`, reached through the
 * `@module_icons` alias and read by module name; a module with no file of
 * its own is drawn with `generic.svg`. Each is a 24 by 24 line drawing in
 * `currentColor`, so the row that holds it tints it.
 */

const GENERIC_GLYPH = "generic";

/** Every glyph's markup by module name, read once at build time. */
const GLYPHS: Record<string, string> = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>("@module_icons/*.svg", {
      query: "?raw",
      import: "default",
      eager: true,
    }),
  ).map(([path, markup]) => [moduleNameOf(path), markup]),
);

interface ModuleIconProps {
  /** The module's manifest name. */
  name: string;
  size?: number;
}

export function ModuleIcon({ name, size = 16 }: ModuleIconProps) {
  const markup = GLYPHS[name] ?? GLYPHS[GENERIC_GLYPH] ?? "";
  return (
    <span
      className="module_icon"
      style={{ width: size, height: size }}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}

/** The module a glyph file is named after. */
function moduleNameOf(path: string): string {
  const file = path.split("/").pop() ?? "";
  return file.endsWith(".svg") ? file.slice(0, -".svg".length) : file;
}
