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
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  CloudcliConfigUpdate,
  CloudcliDeviceView,
  CloudcliInstance,
} from "../api_types";

import "./cloudcli_panels.css";

/**
 * CloudCLI on one machine: which accounts it runs for.
 *
 * Each instance is one account on one port. A client opens it at the
 * machine's address with a one-time token the hub mints, so the panel shows
 * no link to it. A Windows machine installs and starts the instances as their
 * account only with that account's login, picked per instance from the
 * Credentials page.
 */

/** CloudCLI's source, which its AGPL-3.0 license names. */
const SOURCE_URL = "https://github.com/siteboon/claudecodeui";

/** The port a new instance is offered: the one after the highest in use. */
const FIRST_PORT = 3001;

interface CloudcliPanelsProps {
  /** The machine whose CloudCLI this is. */
  deviceId: string;
  /** Where the module answers: `/agent/module/cloudcli`. */
  basePath: string;
  isEditable: boolean;
  /** Whether the machine is Windows, which starts each instance with a login. */
  isWindows: boolean;
}

/** The form's own fields; the machine they are written to is the page's. */
type CloudcliDraft = Omit<CloudcliConfigUpdate, "device_id">;

export function CloudcliPanels({
  deviceId,
  basePath,
  isEditable,
  isWindows,
}: CloudcliPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<CloudcliDeviceView>(
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
  const [notice, setNotice] = useState<string | null>(null);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 240 }} />;
  }

  const reported = new Map(
    saved.instances.map((instance) => [instance.account, instance]),
  );

  const updateInstance = (index: number, patch: Partial<CloudcliInstance>) => {
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
      instances: [
        ...draft.instances,
        { account: "", port: highest + 1, login_id: "" },
      ],
    });
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    const request: CloudcliConfigUpdate = { device_id: deviceId, ...draft };
    try {
      resource.setData(
        await apiPost<CloudcliDeviceView>(`${basePath}/set`, request),
      );
      setNotice(t("ui.api.applied"));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <>
      <div className="notice">
        <Icon name="alert" size={15} />
        <div className="notice_body">
          {t("ui.cloudcli.license")}{" "}
          <a href={SOURCE_URL} target="_blank" rel="noreferrer">
            {t("ui.cloudcli.license_link")}
          </a>
        </div>
      </div>

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.cloudcli.instances_title")}</h2>
          <button
            type="button"
            className="button button--small"
            disabled={!isEditable}
            onClick={addInstance}
          >
            <Icon name="plus" size={13} />
            {t("ui.cloudcli.add")}
          </button>
        </div>
        <p className="field_hint">{t("ui.cloudcli.instances_hint")}</p>
        {draft.instances.length === 0 && (
          <p className="field_hint">{t("ui.cloudcli.empty")}</p>
        )}
        {draft.instances.map((instance, index) => {
          const seen = reported.get(instance.account);
          const isRunning = seen?.is_running === true;
          return (
            <div className="cloudcli_instance" key={index}>
              <Picker
                options={saved.accounts.map((account) => ({
                  id: account,
                  name: account,
                }))}
                value={instance.account}
                onChange={(account) => updateInstance(index, { account })}
                label={t("ui.cloudcli.account")}
                placeholder={t("ui.cloudcli.account_placeholder")}
                isTyped
              />
              <label className="field cloudcli_instance_port">
                <span className="field_label">{t("ui.cloudcli.port")}</span>
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
                  ? t("ui.cloudcli.running")
                  : t("ui.cloudcli.stopped")}
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
                {t("ui.cloudcli.remove")}
              </button>
              {isWindows && (
                <div className="cloudcli_instance_login">
                  <VaultPicker
                    kind="login"
                    value={instance.login_id === "" ? null : instance.login_id}
                    onChange={(loginId) =>
                      updateInstance(index, { login_id: loginId ?? "" })
                    }
                    label={t("ui.cloudcli.login", {
                      account: instance.account,
                    })}
                    hint={t("ui.cloudcli.login_hint")}
                  />
                </div>
              )}
              {seen !== undefined && seen.code !== "" && (
                <span className="field_error cloudcli_instance_error">
                  {describeCode(seen.code, instance)}
                </span>
              )}
            </div>
          );
        })}
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label={t("ui.cloudcli.apply")}
          hint={t("ui.cloudcli.apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          error={error}
          notice={notice}
          onReset={() => {
            reset();
            setError(null);
            setNotice(null);
          }}
          onApply={() => void apply()}
        />
      </section>
    </>
  );
}

/** What the form starts from: the instances as saved. */
function draftOf(view: CloudcliDeviceView): CloudcliDraft {
  return {
    instances: view.instances.map((instance) => ({
      account: instance.account,
      port: instance.port,
      login_id: instance.login_id,
    })),
  };
}

/** Why an instance does not run, worded from the code the machine reported. */
function describeCode(code: string, instance: CloudcliInstance): string {
  const key = `code.${code}`;
  return hasWord(key)
    ? t(key, { account: instance.account, port: instance.port })
    : t("ui.modules.failed_code", { code });
}
