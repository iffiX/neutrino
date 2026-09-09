import { AgentServicePage } from "../components/agent_service_page";
import { ContainersPanels } from "../components/containers_panels";

/**
 * Containers, on whichever managed machine runs podman.
 *
 * The page is the shared Agent-group frame; everything below the machine
 * chips is containers_panels.tsx, pointed at the picked machine.
 */

const WORDING = {
  title: "Containers",
  moduleName: "podman",
};

export function ContainersPage() {
  return (
    <AgentServicePage title={WORDING.title} moduleName={WORDING.moduleName}>
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
