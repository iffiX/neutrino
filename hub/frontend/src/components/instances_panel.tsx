import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { VaultPicker } from "./vault_picker";
import { apiPath, apiPost, describeError } from "../api_client";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { ModuleDescriptor } from "../module_descriptors";
import type {
  CloudcliConfigUpdate,
  CloudcliDeviceView,
  CodeServerConfigUpdate,
  CodeServerDeviceView,
  VscodeConfigUpdate,
  VscodeDeviceView,
} from "../api_types";

import "./instances_panel.css";

/**
 * A program run as a person's account on one machine: which accounts it
 * runs for.
 *
 * Each instance is one account on one port behind the agent's forwarder. A
 * client opens it with the token the hub hands, so the panel shows no link
 * to it. The module's own words, the port a first instance is offered and
 * whether a Windows machine runs each instance with a login picked from the
 * Credentials page come from its descriptor; the view the hub answers is
 * the module's own model.
 */

/** The view of any program run as an account, each the hub's own model. */
type InstancesDeviceView =
  VscodeDeviceView | CodeServerDeviceView | CloudcliDeviceView;

/** The body of a set, the module's own: a module whose instances name a
 * login sends it, the other sends the account and the port alone. */
type InstancesConfigUpdate =
  VscodeConfigUpdate | CodeServerConfigUpdate | CloudcliConfigUpdate;

/** One instance as the form holds it; `login_id` is sent only where the
 * module's instances name one. */
interface InstanceDraft {
  account: string;
  port: number;
  login_id: string;
}

/** The form's own fields; the machine they are written to is the page's. */
interface InstancesDraft {
  instances: InstanceDraft[];
}

interface InstancesPanelProps {
  /** The module, as the page's descriptor table describes it. */
  descriptor: ModuleDescriptor;
  /** The machine whose instances these are. */
  deviceId: string;
  /** Where the module answers: `/agent/module/<module>`. */
  basePath: string;
  isEditable: boolean;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Whether the machine is Windows, which starts each instance with a login. */
  isWindows: boolean;
  /** Whether the machine reports the module installing, so no instance runs yet. */
  isInstalling: boolean;
}

export function InstancesPanel({
  descriptor,
  deviceId,
  basePath,
  isEditable,
  want,
  isWindows,
  isInstalling,
}: InstancesPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const words = descriptor.wording;
  const resource = useApiResource<InstancesDeviceView>(
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
  const version = "version" in saved ? saved.version : "";
  const isLoginPicked = descriptor.isLoginNamed && isWindows;

  const updateInstance = (index: number, patch: Partial<InstanceDraft>) => {
    setDraft({
      ...draft,
      instances: draft.instances.map((instance, at) =>
        at === index ? { ...instance, ...patch } : instance,
      ),
    });
  };

  const addInstance = () => {
    const highest = Math.max(
      descriptor.firstPort - 1,
      ...draft.instances.map((instance) => instance.port),
    );
    setDraft({
      ...draft,
      instances: [
        ...draft.instances,
        { account: "", port: highest + 1, login_id: "" },
      ],
    });
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request = requestOf(descriptor, deviceId, draft);
    try {
      resource.setData(
        await apiPost<InstancesDeviceView>(`${basePath}/set`, request),
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
      {words.ownerNotice !== undefined && (
        <p className="field_hint">
          {version === "" || words.ownerNoticeVersion === undefined
            ? t(words.ownerNotice)
            : t(words.ownerNoticeVersion, { version })}
        </p>
      )}
      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t(words.instancesTitle)}</h2>
          <button
            type="button"
            className="button button--small"
            disabled={!isEditable}
            onClick={addInstance}
          >
            <Icon name="plus" size={13} />
            {t(words.add)}
          </button>
        </div>
        <p className="field_hint">{t(words.instancesHint)}</p>
        {draft.instances.length === 0 && (
          <p className="field_hint">{t(words.empty)}</p>
        )}
        {draft.instances.map((instance, index) => {
          const seen = reported.get(instance.account);
          const isRunning = seen?.is_running === true;
          return (
            <div className="instance_row" key={index}>
              <Picker
                options={saved.accounts.map((account) => ({
                  id: account,
                  name: account,
                }))}
                value={instance.account}
                onChange={(account) => updateInstance(index, { account })}
                label={t(words.account)}
                placeholder={t(words.accountPlaceholder)}
                isTyped
              />
              <label className="field instance_row_port">
                <span className="field_label">{t(words.port)}</span>
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
                  ? t(words.running)
                  : descriptor.isInstallingShown && isInstalling
                    ? t("state.installing")
                    : t(words.stopped)}
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
                {t(words.remove)}
              </button>
              {isLoginPicked &&
                words.login !== undefined &&
                words.loginHint !== undefined && (
                  <div className="instance_row_login">
                    <VaultPicker
                      kind="login"
                      value={
                        instance.login_id === "" ? null : instance.login_id
                      }
                      onChange={(loginId) =>
                        updateInstance(index, { login_id: loginId ?? "" })
                      }
                      label={t(words.login, { account: instance.account })}
                      hint={t(words.loginHint)}
                    />
                  </div>
                )}
              {seen !== undefined && seen.code !== "" && (
                <span className="field_error instance_row_error">
                  {describeCode(seen.code, instance)}
                </span>
              )}
            </div>
          );
        })}
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy || settle.isSettling}
          label={t(words.apply)}
          hint={t(words.applyHint)}
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
function draftOf(view: InstancesDeviceView): InstancesDraft {
  return {
    instances: view.instances.map((instance) => ({
      account: instance.account,
      port: instance.port,
      login_id: "login_id" in instance ? instance.login_id : "",
    })),
  };
}

/** The set's body, in the shape the module's own model takes. */
function requestOf(
  descriptor: ModuleDescriptor,
  deviceId: string,
  draft: InstancesDraft,
): InstancesConfigUpdate {
  if (descriptor.isLoginNamed) {
    return {
      device_id: deviceId,
      instances: draft.instances.map(({ account, port, login_id }) => ({
        account,
        port,
        login_id,
      })),
    };
  }
  return {
    device_id: deviceId,
    instances: draft.instances.map(({ account, port }) => ({ account, port })),
  };
}

/** Why an instance does not run, worded from the code the machine reported. */
function describeCode(code: string, instance: InstanceDraft): string {
  const key = `code.${code}`;
  return hasWord(key)
    ? t(key, { account: instance.account, port: instance.port })
    : t("ui.modules.failed_code", { code });
}
