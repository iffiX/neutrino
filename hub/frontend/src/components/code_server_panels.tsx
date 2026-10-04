import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { apiPath, apiPost, describeError } from "../api_client";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  CodeServerConfigUpdate,
  CodeServerDeviceView,
  CodeServerInstance,
} from "../api_types";

import "./code_server_panels.css";

/**
 * code-server on one machine: which accounts it runs for.
 *
 * Each instance is one account on one port. A client opens it through its
 * forward with a one-time token the hub mints, so the panel shows no link to
 * it.
 */

/** The port a new instance is offered: the one after the highest in use. */
const FIRST_PORT = 8443;

interface CodeServerPanelsProps {
  /** The machine whose code-server this is. */
  deviceId: string;
  /** Where the module answers: `/agent/module/code_server`. */
  basePath: string;
  isEditable: boolean;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
}

/** The form's own fields; the machine they are written to is the page's. */
type CodeServerDraft = Omit<CodeServerConfigUpdate, "device_id">;

export function CodeServerPanels({
  deviceId,
  basePath,
  isEditable,
  want,
}: CodeServerPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<CodeServerDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const saved = resource.data;
  const { draft, setDraft, isDirty, reset } = useDraft(saved, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const settle = useSettledApply(saved, want);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 240 }} />;
  }

  const reported = new Map(
    saved.instances.map((instance) => [instance.account, instance]),
  );

  const updateInstance = (
    index: number,
    patch: Partial<CodeServerInstance>,
  ) => {
    setDraft({
      ...draft,
      instances: draft.instances.map((instance, at) =>
        at === index ? { ...instance, ...patch } : instance,
      ),
    });
  };

  const addInstance = () => {
    const highest = Math.max(
      FIRST_PORT - 1,
      ...draft.instances.map((instance) => instance.port),
    );
    setDraft({
      ...draft,
      instances: [...draft.instances, { account: "", port: highest + 1 }],
    });
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: CodeServerConfigUpdate = { device_id: deviceId, ...draft };
    try {
      resource.setData(
        await apiPost<CodeServerDeviceView>(`${basePath}/set`, request),
      );
      settle.begin();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <>
      <p className="field_hint">
        {saved.version === ""
          ? t("ui.code_server.owner_notice")
          : t("ui.code_server.owner_notice_version", {
              version: saved.version,
            })}
      </p>

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.code_server.instances_title")}</h2>
          <button
            type="button"
            className="button button--small"
            disabled={!isEditable}
            onClick={addInstance}
          >
            <Icon name="plus" size={13} />
            {t("ui.code_server.add")}
          </button>
        </div>
        <p className="field_hint">{t("ui.code_server.instances_hint")}</p>
        {draft.instances.length === 0 && (
          <p className="field_hint">{t("ui.code_server.empty")}</p>
        )}
        {draft.instances.map((instance, index) => {
          const seen = reported.get(instance.account);
          const isRunning = seen?.is_running === true;
          return (
            <div className="code_server_instance" key={index}>
              <Picker
                options={saved.accounts.map((account) => ({
                  id: account,
                  name: account,
                }))}
                value={instance.account}
                onChange={(account) => updateInstance(index, { account })}
                label={t("ui.code_server.account")}
                placeholder={t("ui.code_server.account_placeholder")}
                isTyped
              />
              <label className="field code_server_instance_port">
                <span className="field_label">{t("ui.code_server.port")}</span>
                <input
                  className="input"
                  type="number"
                  min={1024}
                  max={65535}
                  value={instance.port}
                  onChange={(event) =>
                    updateInstance(index, { port: Number(event.target.value) })
                  }
                />
              </label>
              <span className={`badge ${isRunning ? "badge--ok" : ""}`}>
                {isRunning
                  ? t("ui.code_server.running")
                  : t("ui.code_server.stopped")}
              </span>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() =>
                  setDraft({
                    ...draft,
                    instances: draft.instances.filter((_, at) => at !== index),
                  })
                }
              >
                {t("ui.code_server.remove")}
              </button>
              {seen !== undefined && seen.code !== "" && (
                <span className="field_error code_server_instance_error">
                  {describeCode(seen.code, instance)}
                </span>
              )}
            </div>
          );
        })}
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy || settle.isSettling}
          label={t("ui.code_server.apply")}
          hint={t("ui.code_server.apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          error={error}
          notice={
            settle.isApplied && !isFailing(saved) ? t("ui.api.applied") : null
          }
          onReset={() => {
            reset();
            setError(null);
            settle.clear();
          }}
          onApply={() => void apply()}
        />
      </section>
    </>
  );
}

/** What the form starts from: the instances as saved. */
function draftOf(view: CodeServerDeviceView): CodeServerDraft {
  return {
    instances: view.instances.map((instance) => ({
      account: instance.account,
      port: instance.port,
    })),
  };
}

/** Why an instance does not run, worded from the code the machine reported. */
function describeCode(code: string, instance: CodeServerInstance): string {
  const key = `code.${code}`;
  return hasWord(key)
    ? t(key, { account: instance.account, port: instance.port })
    : t("ui.modules.failed_code", { code });
}
