import { codeParams } from "./code_params";
import { hasWord, t } from "./i18n";
import { withModuleTitle } from "./module_title";
import type { ModuleTaskStep } from "./api_types";

/** The step that installs one artifact. One with no words of its own reads
 * `ui.modules.step.artifact_alone` in a plan with one of them, and names its
 * artifact in a plan with several. */
export const ARTIFACT_STEP = "artifact";

/** The steps that may read their artifact's own words,
 * `ui.modules.step.<step>.<module>.<artifact>`, each by the param that
 * names the artifact. */
const ARTIFACT_PARAMS: Record<string, string> = {
  artifact: "name",
  pull: "image",
};

/** A step's words with its params, a module it names by its title, or its
 * artifact's own words where the catalog has them; a step the catalog lacks
 * reads as its name. `artifactCount` counts the plan's `artifact` steps. */
export function stepWords(
  step: ModuleTaskStep,
  module: string,
  artifactCount: number,
  manifestTitles: Record<string, string>,
): string {
  const param = ARTIFACT_PARAMS[step.name];
  if (param !== undefined) {
    const own = `ui.modules.step.${step.name}.${module}.${String(step.params[param] ?? "")}`;
    if (hasWord(own)) {
      return t(own);
    }
  }
  if (step.name === ARTIFACT_STEP && artifactCount === 1) {
    return t("ui.modules.step.artifact_alone");
  }
  const key = `ui.modules.step.${step.name}`;
  return hasWord(key)
    ? t(key, withModuleTitle(codeParams(step.params), manifestTitles))
    : step.name;
}
