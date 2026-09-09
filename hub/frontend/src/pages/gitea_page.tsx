import { AgentServicePage } from "../components/agent_service_page";
import { GiteaPanels } from "../components/gitea_panels";

/**
 * Gitea, on whichever managed machine runs it.
 *
 * The page is the shared Agent-group frame; everything below the machine
 * chips is gitea_panels.tsx, pointed at the picked machine.
 */

const WORDING = {
  title: "Gitea",
  moduleName: "gitea",
};

export function GiteaPage() {
  return (
    <AgentServicePage title={WORDING.title} moduleName={WORDING.moduleName}>
      {(target) => (
        <GiteaPanels
          basePath={target.basePath}
          isEditable={target.isEditable}
        />
      )}
    </AgentServicePage>
  );
}
