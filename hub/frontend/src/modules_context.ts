import { createContext } from "react";

import type { ApiResource } from "./use_api_resource";
import type { ModulesResponse } from "./api_types";

/**
 * The one view of the managed modules, shared by the shell and its pages.
 *
 * The sidebar decides which optional pages to show from the same list the
 * Modules page acts on. With each holding its own copy, disabling samba
 * changed one and not the other, and the rail kept a Samba entry until
 * something happened to refetch it — so there is one copy, and an action
 * folds its result into it for both to see at once.
 */
export const ModulesContext =
  createContext<ApiResource<ModulesResponse> | null>(null);
