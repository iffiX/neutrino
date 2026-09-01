import { useEffect, useState } from "react";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { NodesPanel } from "../components/nodes_panel";
import { SocksPortsPanel } from "../components/socks_ports_panel";
import { StringListEditor } from "../components/string_list_editor";
import { ToggleSwitch } from "../components/toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import type { DnsServer, ApplyResult, ProxySettings } from "../api_types";

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

const GROUP_FIELDS: Record<GroupName, (keyof ProxySettings)[]> = {
  route: [
    "is_proxy_enabled",
    "is_local_proxy_enabled",
    "is_geoip_split_enabled",
    "direct_domains",
    "direct_ips",
    "remote_dns",
    "direct_dns",
  ],
};

export function ProxyPage() {
  const resource = useApiResource<ProxySettings>("/proxy");

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
        <h1>Proxy</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (draft === null) {
    return (
      <div className="page">
        <h1>Proxy</h1>
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Proxy</h1>
          <span
            className={`badge ${draft.is_proxy_enabled ? "badge--ok" : "badge--warn"}`}
          >
            {draft.is_proxy_enabled ? "on" : "off"}
          </span>
        </div>
      </div>

      <NodesPanel />

      <section
        className={`settings_group ${isGroupDirty("route") ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>Route</h2>
        </div>
        <p className="field_hint">
          Whose traffic goes through the exit nodes, and which destinations are
          left out of it.
        </p>

        {/* Who goes through the proxy: the machines behind the gateway, and
            the gateway itself. Two independent answers to one question, so
            they sit together rather than one being buried in the rules. */}
        <ToggleSwitch
          isOn={draft.is_proxy_enabled}
          onChange={(isOn) => updateDraft({ is_proxy_enabled: isOn })}
          label="Send LAN traffic through the proxy"
          description="The machines behind the gateway. Off takes the proxy out of their path entirely: the firewall stops diverting, names resolve directly, and no exit node is used. Reach for it to find out whether the proxy is what is broken."
        />
        <ToggleSwitch
          isOn={draft.is_local_proxy_enabled}
          onChange={(isOn) => updateDraft({ is_local_proxy_enabled: isOn })}
          isDisabled={!draft.is_proxy_enabled}
          label="Send this gateway's own traffic through the proxy"
          description="The box itself, tailscaled included. This is the way back in when Tailscale cannot reach its control plane over the local link. LAN clients are unaffected either way."
        />

        <div className="proxy_switches">
          <section
            className={`proxy_switch_card proxy_switch_card--wide ${draft.is_geoip_split_enabled ? "proxy_switch_card--on" : ""}`}
          >
            <div className="proxy_switch_head">
              <span className="proxy_switch_title">
                <Icon name="globe" size={16} className="proxy_switch_icon" />
                GeoIP split routing
              </span>
              <ToggleSwitch
                isOn={draft.is_geoip_split_enabled}
                onChange={(isOn) =>
                  updateDraft({ is_geoip_split_enabled: isOn })
                }
                label="GeoIP split routing"
              />
            </div>
            <div className="proxy_switch_body">
              <p>
                Domains and IPs matching the direct lists below leave straight
                out of the WAN. Everything else goes through the JustMySocks
                balancer. Turn this off to send absolutely every LAN request
                through the proxy.
              </p>
              <div className="proxy_switch_flow">
                <span>LAN</span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span className="badge badge--ok">direct list</span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span>WAN</span>
                <span className="proxy_switch_flow_arrow">·</span>
                <span className="badge badge--accent">everything else</span>
                <span className="proxy_switch_flow_arrow">→</span>
                <span>exit node</span>
              </div>
            </div>
          </section>
        </div>

        <div className="proxy_lists">
          <section className="proxy_subcard">
            <div className="card_header">
              <div className="card_title">
                <h2>Direct domains</h2>
                <span className="badge">{draft.direct_domains.length}</span>
              </div>
            </div>
            <StringListEditor
              label="Domains that bypass the proxy"
              description="xray rule syntax: geosite:cn, domain:example.com, keyword:baidu."
              placeholder="geosite:cn"
              values={draft.direct_domains}
              onChange={(values) => updateDraft({ direct_domains: values })}
            />
          </section>

          <section className="proxy_subcard">
            <div className="card_header">
              <div className="card_title">
                <h2>Direct IPs</h2>
                <span className="badge">{draft.direct_ips.length}</span>
              </div>
            </div>
            <StringListEditor
              label="IP ranges that bypass the proxy"
              description="xray rule syntax: geoip:cn, geoip:private, 10.0.0.0/8."
              placeholder="geoip:cn"
              values={draft.direct_ips}
              onChange={(values) => updateDraft({ direct_ips: values })}
            />
          </section>
        </div>

        <section className="proxy_subcard">
          <div className="card_header">
            <div className="card_title">
              <h2>DNS</h2>
            </div>
          </div>
          <div className="proxy_dns_grid">
            <div className="field">
              <span className="field_label">
                Remote resolver (proxied names)
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
              <span className="field_hint">Resolved at the exit node.</span>
            </div>

            <div className="field">
              <span className="field_label">
                Direct resolver (bypassed names)
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
                Answers direct-list names, and all names while the proxy is off.
              </span>
            </div>
          </div>
        </section>

        <ApplyBar
          isDirty={isGroupDirty("route")}
          isBusy={busyGroup === "route"}
          label="Apply route"
          hint="Rewrites the xray routing rules and reloads the proxy."
          warning="Restarts the proxy; connections through it drop."
          error={errors.route ?? null}
          notice={notice.route ?? null}
          onReset={() => resetGroup("route")}
          onApply={() => void applyGroup("route")}
        />
      </section>

      <SocksPortsPanel
        settings={draft}
        onApplied={(saved) => {
          resource.setData(saved);
          setDraft(saved);
        }}
      />
    </div>
  );
}
