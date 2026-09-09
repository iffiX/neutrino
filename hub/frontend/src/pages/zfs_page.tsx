import { AgentServicePage } from "../components/agent_service_page";
import { ZfsPanels } from "../components/zfs_panels";

/**
 * ZFS, on whichever managed machine holds the pools.
 *
 * The page is the shared Agent-group frame; everything below the machine
 * chips is zfs_panels.tsx, pointed at the picked machine.
 */

const WORDING = {
  title: "ZFS",
  moduleName: "zfs",
};

export function ZfsPage() {
  return (
    <AgentServicePage title={WORDING.title} moduleName={WORDING.moduleName}>
      {(target) => (
        <ZfsPanels basePath={target.basePath} isEditable={target.isEditable} />
      )}
    </AgentServicePage>
  );
}
