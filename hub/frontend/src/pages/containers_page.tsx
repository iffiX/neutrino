import { AgentServicePage } from "../components/agent_service_page";
import { ContainersPanels } from "../components/containers_panels";
import { t, useLanguage } from "../i18n";

/**
 * Containers, on whichever managed machine runs podman.
 *
 * The page is the shared Agent-group frame; everything below the machine
 * chips is containers_panels.tsx, pointed at the picked machine.
 */

const MODULE_NAME = "podman";

export function ContainersPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <AgentServicePage title={t("ui.containers.title")} moduleName={MODULE_NAME}>
      {(target) => (
        <ContainersPanels
          deviceId={target.deviceId}
          basePath={target.basePath}
          isEditable={target.isEditable}
        />
      )}
    </AgentServicePage>
  );
}
