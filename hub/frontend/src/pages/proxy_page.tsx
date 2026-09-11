import { useEffect, useState } from "react";

import { ApplyBar } from "../components/apply_bar";
import { DeadExitsNotice } from "../components/dead_exits_notice";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { NodesPanel } from "../components/nodes_panel";
import { SocksPortsPanel } from "../components/socks_ports_panel";
import { StringListEditor } from "../components/string_list_editor";
import { ToggleSwitch } from "../components/toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { computeActiveExits, primaryExitTag } from "../active_exits";
import { t, useLanguage } from "../i18n";
import { describeProxy } from "../proxy_status";
import type { ProxyTone } from "../proxy_status";
import { useApiResource } from "../use_api_resource";
import { useLiveStats } from "../use_live_stats";
import type {
  DnsServer,
  ApplyResult,
  NetworkView,
  ProxySettings,
} from "../api_types";

import "./proxy_page.css";

/**
 * Everything about going out through a proxy, in the order the questions come.
 *
 * Is it on, which exits does it have, and how is traffic split between them and
 * the direct path. Those used to be two pages — Nodes and Proxy — split by
 * implementation rather than by question, so "why is my traffic leaving the
 * wrong way" meant reading both and holding them together in your head.
 *
 * The master switch is first and deliberately blunt. Turning it off takes the
 * proxy out of the path entirely: the firewall stops diverting, names resolve
 * directly, and no exit node is used or needed. It is the honest thing to reach
 * for when working out whether the proxy is what is broken.
 */

/**
 * Which settings move together.
 *
 * Each group is one framed box with one apply button, and a box is the whole
 * unit of change: applying it sends its own fields laid over what the gateway
 * already has, so a half-finished edit in another box is never written by
 * accident.
 */
type GroupName = "route";

/** The badge each proxy tone wears, matching the strip's own colouring. */
const BADGE_TONES: Record<ProxyTone, string> = {
  proxy: "badge--accent",
  direct: "badge--warn",
  offline: "badge--error",
};

const GROUP_FIELDS: Record<GroupName, (keyof ProxySettings)[]> = {
  route: [
    "is_proxy_enabled",
    "is_local_proxy_enabled",
    "is_direct_fallback_enabled",
    "is_geoip_split_enabled",
    "direct_domains",
    "direct_ips",
    "remote_dns",
    "direct_dns",
  ],
};

export function ProxyPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ProxySettings>("/proxy");
  // The LAN scope only means something on a box that forwards a network, and
  // which boxes do is the network mode's answer.
  const network = useApiResource<NetworkView>("/network");
  const { frames, latestFrame } = useLiveStats();

  const [draft, setDraft] = useState<ProxySettings | null>(null);
  const [busyGroup, setBusyGroup] = useState<GroupName | null>(null);
  const [notice, setNotice] = useState<Partial<Record<GroupName, string>>>({});
  const [errors, setErrors] = useState<Partial<Record<GroupName, string>>>({});

  useEffect(() => {
    if (resource.data !== null) {
      setDraft(resource.data);
    }
  }, [resource.data]);

  const updateDraft = (patch: Partial<ProxySettings>) => {
    setNotice({});
    setDraft((current) =>
      current === null ? current : { ...current, ...patch },
    );
  };

  /** Whether a group's fields differ from what the gateway last returned. */
  const isGroupDirty = (group: GroupName): boolean => {
    if (draft === null || resource.data === null) {
      return false;
    }
    return GROUP_FIELDS[group].some(
      (field) =>
        JSON.stringify(draft[field]) !== JSON.stringify(resource.data![field]),
    );
  };

  /**
   * Save one group's fields and load them.
   *
   * Only this group's fields are sent, laid over what the gateway last
   * returned, so applying one box never writes another box's unsaved edits.
   */
  const applyGroup = async (group: GroupName) => {
    if (draft === null || resource.data === null) {
      return;
    }
    setBusyGroup(group);
    setErrors({});
    setNotice({});
    try {
      const payload = { ...resource.data };
      for (const field of GROUP_FIELDS[group]) {
        Object.assign(payload, { [field]: draft[field] });
      }
      const saved = await apiPut<ProxySettings>("/proxy", payload);
      const result = await apiPost<ApplyResult>("/proxy/apply");
      resource.setData(saved);
      setDraft((current) =>
        current === null ? saved : { ...current, ...saved },
      );
      if (!result.is_applied) {
        setErrors({ [group]: result.message });
        return;
      }
      setNotice({ [group]: result.message });
    } catch (cause: unknown) {
      setErrors({ [group]: describeError(cause) });
    } finally {
      setBusyGroup(null);
    }
  };

  const resetGroup = (group: GroupName) => {
    if (resource.data === null) {
      return;
    }
    const saved = resource.data;
    setNotice({});
    setErrors({});
    setDraft((current) => {
      if (current === null) {
        return current;
      }
      const next = { ...current };
      for (const field of GROUP_FIELDS[group]) {
        Object.assign(next, { [field]: saved[field] });
      }
      return next;
    });
  };

  const updateDns = (
    key: "remote_dns" | "direct_dns",
    patch: Partial<DnsServer>,
  ) => {
    setNotice({});
    setDraft((current) =>
      current === null
        ? current
        : { ...current, [key]: { ...current[key], ...patch } },
    );
  };

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{t("ui.proxy.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (draft === null) {
    return (
      <div className="page">
        <h1>{t("ui.proxy.title")}</h1>
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    );
  }

  const mode = network.data?.mode ?? null;
  const isForwardingMode =
    mode === null || mode === "router" || mode === "side_gateway";
  // The same describer the strip's chip uses, so the page and its thumbnail
  // are one answer rather than two. An on/off badge here used to mean "is a
  // node enabled", which a server could show as `on` beside a strip saying
  // `direct` — both true, about different questions.
  const proxy = describeProxy(
    latestFrame,
    primaryExitTag(computeActiveExits(frames)),
  );

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.proxy.title")}</h1>
          <span className={`badge ${BADGE_TONES[proxy.tone]}`}>
            {proxy.scope}
          </span>
          {proxy.exit !== "" && (
            <span className="badge badge--accent">{proxy.exit}</span>
          )}
        </div>
      </div>

      <DeadExitsNotice isFallingBack={draft.is_direct_fallback_enabled} />

      <NodesPanel onNodesChanged={resource.reload} />

      <section
        className={`settings_group ${isGroupDirty("route") ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.proxy.route_title")}</h2>
        </div>
        <p className="field_hint">{t("ui.proxy.route_hint")}</p>

        {/* Who goes through the proxy: the machines this box forwards for,
            and the box itself. Two independent answers to one question, so
            they sit together rather than one being buried in the rules. */}
        <ToggleSwitch
          isOn={draft.is_proxy_enabled}
          onChange={(isOn) => updateDraft({ is_proxy_enabled: isOn })}
          isDisabled={!isForwardingMode}
          label={t("ui.proxy.lan_toggle")}
          description={
            isForwardingMode
              ? t("ui.proxy.lan_toggle_description")
              : t("ui.proxy.lan_toggle_description_server")
          }
        />
        <ToggleSwitch
          isOn={draft.is_local_proxy_enabled}
          onChange={(isOn) => updateDraft({ is_local_proxy_enabled: isOn })}
          label={t("ui.proxy.local_toggle")}
          description={t("ui.proxy.local_toggle_description")}
        />

        <ToggleSwitch
          isOn={draft.is_direct_fallback_enabled}
          onChange={(isOn) => updateDraft({ is_direct_fallback_enabled: isOn })}
          label={t("ui.proxy.fallback_toggle")}
          description={t("ui.proxy.fallback_toggle_description")}
        />

        <div className="proxy_switches">
          <section
            className={`proxy_switch_card proxy_switch_card--wide ${draft.is_geoip_split_enabled ? "proxy_switch_card--on" : ""}`}
          >
            <div className="proxy_switch_head">
              <span className="proxy_switch_title">
                <Icon name="globe" size={16} className="proxy_switch_icon" />
                {t("ui.proxy.geoip_title")}
              </span>
              <ToggleSwitch
                isOn={draft.is_geoip_split_enabled}
                onChange={(isOn) =>
                  updateDraft({ is_geoip_split_enabled: isOn })
                }
                label={t("ui.proxy.geoip_title")}
              />
            </div>
            <div className="proxy_switch_body">
              <p>{t("ui.proxy.geoip_body")}</p>
              <div className="proxy_switch_flow">
                <span>LAN</span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span className="badge badge--ok">
                  {t("ui.proxy.geoip_flow_direct")}
                </span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span>WAN</span>
                <span className="proxy_switch_flow_arrow">·</span>
                <span className="badge badge--accent">
                  {t("ui.proxy.geoip_flow_rest")}
                </span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span>{t("ui.proxy.geoip_flow_exit")}</span>
              </div>
            </div>
          </section>
        </div>

        <div className="proxy_lists">
          <section className="proxy_subcard">
            <div className="card_header">
              <div className="card_title">
                <h2>{t("ui.proxy.direct_domains_title")}</h2>
                <span className="badge">{draft.direct_domains.length}</span>
              </div>
            </div>
            <StringListEditor
              label={t("ui.proxy.direct_domains_label")}
              description={t("ui.proxy.direct_domains_description")}
              placeholder="geosite:cn"
              values={draft.direct_domains}
              onChange={(values) => updateDraft({ direct_domains: values })}
            />
          </section>

          <section className="proxy_subcard">
            <div className="card_header">
              <div className="card_title">
                <h2>{t("ui.proxy.direct_ips_title")}</h2>
                <span className="badge">{draft.direct_ips.length}</span>
              </div>
            </div>
            <StringListEditor
              label={t("ui.proxy.direct_ips_label")}
              description={t("ui.proxy.direct_ips_description")}
              placeholder="geoip:cn"
              values={draft.direct_ips}
              onChange={(values) => updateDraft({ direct_ips: values })}
            />
          </section>
        </div>

        <section className="proxy_subcard">
          <div className="card_header">
            <div className="card_title">
              <h2>{t("ui.proxy.dns_title")}</h2>
            </div>
          </div>
          <div className="proxy_dns_grid">
            <div className="field">
              <span className="field_label">
                {t("ui.proxy.remote_dns_label")}
              </span>
              <div className="proxy_dns_pair">
                <input
                  className="input"
                  value={draft.remote_dns.address}
                  onChange={(event) =>
                    updateDns("remote_dns", { address: event.target.value })
                  }
                />
                <input
                  className="input"
                  inputMode="numeric"
                  value={String(draft.remote_dns.port)}
                  onChange={(event) =>
                    updateDns("remote_dns", {
                      port: Number(event.target.value) || 0,
                    })
                  }
                />
              </div>
              <span className="field_hint">
                {t("ui.proxy.remote_dns_hint")}
              </span>
            </div>

            <div className="field">
              <span className="field_label">
                {t("ui.proxy.direct_dns_label")}
              </span>
              <div className="proxy_dns_pair">
                <input
                  className="input"
                  value={draft.direct_dns.address}
                  onChange={(event) =>
                    updateDns("direct_dns", { address: event.target.value })
                  }
                />
                <input
                  className="input"
                  inputMode="numeric"
                  value={String(draft.direct_dns.port)}
                  onChange={(event) =>
                    updateDns("direct_dns", {
                      port: Number(event.target.value) || 0,
                    })
                  }
                />
              </div>
              <span className="field_hint">
                {t("ui.proxy.direct_dns_hint")}
              </span>
            </div>
          </div>
        </section>

        <ApplyBar
          isDirty={isGroupDirty("route")}
          isBusy={busyGroup === "route"}
          label={t("ui.proxy.apply_route")}
          hint={t("ui.proxy.apply_route_hint")}
          warning={t("ui.proxy.warning_restart")}
          error={errors.route ?? null}
          notice={notice.route ?? null}
          onReset={() => resetGroup("route")}
          onApply={() => void applyGroup("route")}
        />
      </section>

      <SocksPortsPanel
        applied={resource.data ?? draft}
        onApplied={(saved) => {
          resource.setData(saved);
          // Only this box's own field: the rest of the page may hold edits
          // nobody has applied yet.
          setDraft((current) =>
            current === null
              ? saved
              : { ...current, socks_ports: saved.socks_ports },
          );
        }}
      />
    </div>
  );
}
