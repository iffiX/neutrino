import { useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  ModuleVersionEntry,
  ModuleVersionSetRequest,
  ModuleVersionView,
} from "../api_types";

import "./module_version_block.css";

/**
 * An installed module's version line: the version installed, the newest
 * listed where the two differ, **Update** to the newest, and **Install
 * another version…**, a dialog of the listed versions newest first with
 * **Follow the tested version** at its top.
 *
 * A locked version, a module whose version follows the system or its image,
 * shows the same line with Update dead and the dialog holding its one
 * version, which cannot be pressed. A version older than the one installed,
 * on a module that moves its data forward, asks first.
 */

const VERSION_PATH = "/agent/module/version";

/** The dialog's top row: follow the tested version. */
const FOLLOW_TESTED = "";

interface ModuleVersionBlockProps {
  deviceId: string;
  module: string;
  /** The module's title in the panel's language. */
  title: string;
  /** Whether a press can be sent: the machine online and the module not in
   * transit. */
  canPress: boolean;
}

export function ModuleVersionBlock({
  deviceId,
  module,
  title,
  canPress,
}: ModuleVersionBlockProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ModuleVersionView>(
    apiPath(VERSION_PATH, { device_id: deviceId, module }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const confirm = useConfirm();
  const [isPicking, setIsPicking] = useState(false);
  const [busyVersion, setBusyVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;

  if (view === null) {
    return resource.error !== null ? (
      <span className="field_error">{resource.error}</span>
    ) : null;
  }

  const isNewer = view.newest !== "" && view.newest !== view.installed;
  const canUpdate = canPress && isNewer && !view.is_locked;
  const canPick = canPress;

  const choose = async (version: string) => {
    setBusyVersion(version);
    setError(null);
    const request: ModuleVersionSetRequest = {
      device_id: deviceId,
      module,
      version,
    };
    try {
      resource.setData(
        await apiPost<ModuleVersionView>(`${VERSION_PATH}/set`, request),
      );
      setIsPicking(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setBusyVersion(null);
    }
  };

  const pick = (entry: ModuleVersionEntry) => {
    if (view.is_data_forward_only && isOlder(view, entry.version)) {
      confirm.ask({
        title: t("ui.modules.downgrade_title", {
          module: title,
          version: entry.version,
        }),
        body: t("ui.modules.downgrade_body", {
          module: title,
          version: entry.version,
        }),
        confirmLabel: t("ui.modules.install_version_confirm"),
        onConfirm: () => void choose(entry.version),
      });
      return;
    }
    void choose(entry.version);
  };

  return (
    <div className="module_version">
      <span className="module_version_line mono">
        {t("ui.modules.version_installed", { version: view.installed })}
        {isNewer && (
          <span className="faint">
            {" · "}
            {t("ui.modules.version_newest", { version: view.newest })}
          </span>
        )}
      </span>
      <span className="module_version_buttons">
        <button
          type="button"
          className="button button--small"
          disabled={!canUpdate || busyVersion !== null}
          onClick={() => void choose(view.newest)}
        >
          {busyVersion === view.newest && !isPicking ? (
            <Spinner size={12} />
          ) : (
            <Icon name="download" size={13} />
          )}
          {t("ui.modules.update")}
        </button>
        <button
          type="button"
          className="button button--small"
          disabled={!canPick}
          onClick={() => setIsPicking(true)}
        >
          {t("ui.modules.install_version")}
        </button>
      </span>
      {error !== null && !isPicking && (
        <span className="field_error module_version_error">{error}</span>
      )}
      {isPicking && (
        <DialogFrame
          title={t("ui.modules.install_version_title", { module: title })}
          icon="download"
          onClose={() => setIsPicking(false)}
        >
          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}
          <div className="module_version_rows">
            {!view.is_locked && (
              <button
                type="button"
                className="module_version_row"
                disabled={busyVersion !== null}
                onClick={() => void choose(FOLLOW_TESTED)}
              >
                <span>{t("ui.modules.version_follow_tested")}</span>
                {view.chosen === "" && <Icon name="check" size={13} />}
              </button>
            )}
            {view.versions.map((entry) => (
              <button
                key={entry.version}
                type="button"
                className="module_version_row"
                disabled={view.is_locked || busyVersion !== null}
                onClick={() => pick(entry)}
              >
                <span className="mono">{entry.version}</span>
                {entry.is_tested && (
                  <span className="badge badge--ok">
                    {t("ui.modules.version_tested")}
                  </span>
                )}
                {entry.is_untested && (
                  <span className="badge badge--warn">
                    {t("ui.modules.version_untested")}
                  </span>
                )}
                {busyVersion === entry.version && <Spinner size={12} />}
                {entry.version === view.installed && (
                  <Icon name="check" size={13} />
                )}
              </button>
            ))}
          </div>
        </DialogFrame>
      )}
      {confirm.modal}
    </div>
  );
}

/** Whether a listed version comes after the installed one, newest first. */
function isOlder(view: ModuleVersionView, version: string): boolean {
  const installedAt = view.versions.findIndex(
    (entry) => entry.version === view.installed,
  );
  const versionAt = view.versions.findIndex(
    (entry) => entry.version === version,
  );
  return installedAt >= 0 && versionAt > installedAt;
}
