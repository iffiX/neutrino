import { AgentServicePage } from "../components/agent_service_page";
import { SambaPanels } from "../components/samba_panels";

/**
 * Samba, on whichever managed machine serves it.
 *
 * The page is the shared Agent-group frame; everything below the machine
 * chips is samba_panels.tsx, pointed at the picked machine.
 */

const WORDING = {
  title: "Samba",
  moduleName: "samba",
};

export function SambaPage() {
  return (
    <AgentServicePage title={WORDING.title} moduleName={WORDING.moduleName}>
      {(target) => (
        <SambaPanels
          basePath={target.basePath}
          isEditable={target.isEditable}
        />
      )}
    </AgentServicePage>
  );
}
