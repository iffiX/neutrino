import { useState } from "react";

import { ContainersMachineFields } from "./containers_machine_fields";
import { DialogFrame } from "./dialog_frame";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { machineDiskError } from "../podman_machine";
import type { MachineSize } from "../podman_machine";
import { useApiResource } from "../use_api_resource";
import type {
  PodmanDeviceView,
  PodmanMachineUpdate,
  PodmanNewMachineView,
} from "../api_types";

/**
 * The size of the default account's Podman machine, asked before an Install
 * on a Windows or macOS machine whose Run settings the hub does not hold yet.
 *
 * The machine's CPUs, memory and disk limit, each filled with the number the
 * machine reports for a new machine. **Install** writes the Run settings
 * with the numbers shown and hands on to the press. Cancel writes nothing.
 */

const NEW_MACHINE_PATH = "/agent/module/podman/new_machine";
const MACHINE_SET_PATH = "/agent/module/podman/machine/set";

/** The system whose disk limit is at least 1. */
const WINDOWS_OS = "windows";

interface ContainersAccountModalProps {
  deviceId: string;
  /** The system the machine's agent reports. */
  platformOs: string;
  /** The module being installed, counted in the memory hint. */
  module: string;
  /** Called once the Run settings hold the numbers. */
  onChosen: () => void;
  onCancel: () => void;
}

export function ContainersAccountModal({
  deviceId,
  platformOs,
  module,
  onChosen,
  onCancel,
}: ContainersAccountModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const newMachine = useApiResource<PodmanNewMachineView>(
    apiPath(NEW_MACHINE_PATH, { device_id: deviceId, module }),
  );
  const [edits, setEdits] = useState<Partial<MachineSize>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const numbers = newMachine.data;

  const isWindows = platformOs === WINDOWS_OS;
  const size: MachineSize = {
    cpus: edits.cpus ?? numbers?.cpus ?? 0,
    memory_gib: edits.memory_gib ?? numbers?.memory_gib ?? 0,
    disk_gib: edits.disk_gib ?? numbers?.disk_gib ?? 0,
  };
  const currentDisk = numbers?.disk_gib_now ?? 0;
  const needGib = numbers?.need_gib ?? 0;
  const memoryNow = size.memory_gib || (numbers?.memory_gib ?? 0);
  const loadError = numbers === null ? newMachine.error : null;
  const isReady =
    numbers !== null &&
    !newMachine.isLoading &&
    newMachine.error === null &&
    !isSaving &&
    machineDiskError(size.disk_gib, currentDisk, isWindows) === null;

  const shownError = error ?? (loadError === null ? newMachine.error : null);

  const writeMachine = async () => {
    const request: PodmanMachineUpdate = { device_id: deviceId, ...size };
    await apiPost<PodmanDeviceView>(MACHINE_SET_PATH, request);
  };

  const confirm = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await writeMachine();
      onChosen();
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsSaving(false);
    }
  };

  const cancel = () => {
    if (!isSaving) {
      onCancel();
    }
  };

  return (
    <DialogFrame
      title={t("ui.containers.run_title")}
      icon="server"
      hasHeadClose={false}
      foot={
        <>
          <button
            type="button"
            className="button"
            disabled={isSaving}
            onClick={cancel}
          >
            {t("ui.confirm.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={!isReady}
            onClick={() => void confirm()}
          >
            {isSaving ? (
              <Spinner size={13} />
            ) : (
              <Icon name="download" size={14} />
            )}
            {t("ui.modules.install")}
          </button>
        </>
      }
      onClose={cancel}
    >
      {loadError !== null ? (
        <ErrorPanel message={loadError} onRetry={newMachine.reload} />
      ) : numbers === null ? (
        <div className="skeleton" style={{ height: 64 }} />
      ) : (
        <ContainersMachineFields
          size={size}
          currentDisk={currentDisk}
          isWindows={isWindows}
          memoryNeedGib={needGib > memoryNow ? needGib : null}
          isDisabled={isSaving}
          onChange={(change) => {
            setEdits({ ...edits, ...change });
          }}
        />
      )}
      {shownError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{shownError}</div>
        </div>
      )}
    </DialogFrame>
  );
}
