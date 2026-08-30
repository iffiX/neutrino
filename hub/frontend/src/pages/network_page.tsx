import { useEffect, useMemo, useState } from "react";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { NetworkDiagram } from "../components/network_diagram";
import { PasswordInput } from "../components/password_input";
import { SignalBars } from "../components/signal_bars";
import { StatusDot } from "../components/status_dot";
import { ToggleSwitch } from "../components/toggle_switch";
import { WifiScanPanel } from "../components/wifi_scan_panel";
import { apiDelete, apiPut, describeError } from "../api_client";
import {
  isInterfaceDraftValid,
  validateInterface,
} from "../network_validation";
import type { InterfaceErrors, ServedNetwork } from "../network_validation";
import { useApiResource } from "../use_api_resource";
import type {
  DevicesResponse,
  InterfaceRole,
  InterfaceSettings,
  InterfaceView,
  NetworkOptions,
  NetworkView,
  UplinkIntent,
} from "../api_types";

import "./network_page.css";

/**
 * What each interface is for, and what it is doing.
 *
 * The page is a diagram of the wiring, a tab per interface, and one form for
 * whichever is selected. Roles rather than fixed names: an interface is an
 * uplink, a network the box serves, or unused, and the role decides what there
 * is to configure. That is what lets the same page describe a box with two
 * LANs, or one reaching the internet over Wi-Fi.
 *
 * Each interface saves and applies on its own. Applying the whole page at once
 * would mean a mistake in the Wi-Fi settings could take the wired LAN down
 * with it, and the wired LAN is how you get back in.
 */

const INTENT_OPTIONS: { value: UplinkIntent; label: string; hint: string }[] = [
  {
    value: "auto",
    label: "Automatic",
    hint: "Let the gateway place this uplink.",
  },
  {
    value: "primary",
    label: "Prefer this one",
    hint: "Pin it ahead of the ranking.",
  },
  {
    value: "backup_only",
    label: "Backup only",
    hint: "Use only when no other uplink is left.",
  },
];

const ROLE_OPTIONS: { value: InterfaceRole; label: string; hint: string }[] = [
  { value: "wan", label: "WAN", hint: "An uplink to the internet" },
  { value: "lan", label: "LAN", hint: "A network the gateway serves" },
  { value: "split", label: "Split", hint: "A trunk sliced into VLANs" },
  { value: "disabled", label: "Disabled", hint: "Left alone" },
];

const VLAN_ID_MIN = 1;
const VLAN_ID_MAX = 4094;

/** A fresh VLAN interface, born disabled so adding it changes nothing yet. */
function newVlanSettings(parent: string, id: number): InterfaceSettings {
  return {
    name: `${parent}.${id}`,
    role: "disabled",
    wan: {
      method: "dhcp",
      address: null,
      prefix_len: 24,
      gateway: null,
      intent: "auto",
      cloned_mac: null,
    },
    lan: {
      address: "",
      prefix_len: 24,
      is_dhcp_enabled: true,
      dhcp_range_start: "",
      dhcp_range_end: "",
      dhcp_lease_time: "12h",
      upstream_gateway: null,
    },
    wifi: { ssid: "", ap_ssid: "", ap_passphrase: "", ap_band: "bg" },
    vlan: { parent, id },
  };
}

export function NetworkPage() {
  const network = useApiResource<NetworkView>("/network");
  // The cheap list endpoint, no ARP sweep: the diagram only wants to draw
  // what is already known.
  const deviceList = useApiResource<DevicesResponse>("/devices");

  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [draft, setDraft] = useState<InterfaceSettings | null>(null);
  // The VLAN list is drafted beside the settings: adding or crossing one off
  // lights the frame like any other edit, and Apply is what makes it real.
  const [vlanIds, setVlanIds] = useState<number[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [options, setOptions] = useState<NetworkOptions | null>(null);
  const [isSavingOptions, setIsSavingOptions] = useState(false);
  const [optionsNotice, setOptionsNotice] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  useEffect(() => {
    if (network.data === null) {
      return;
    }
    setOptions({
      is_ssh_from_wan_allowed: network.data.is_ssh_from_wan_allowed,
      uplink_policy: network.data.uplink_policy,
      is_inter_lan_allowed: network.data.is_inter_lan_allowed,
    });
  }, [network.data]);

  // Memoised so `selected` keeps the same identity between renders while the
  // data has not changed, which is what lets the draft effect below depend on
  // it without resetting the form under the user's hands.
  const interfaces = useMemo(
    () => network.data?.interfaces ?? [],
    [network.data],
  );
  const selected = useMemo(
    () =>
      interfaces.find((entry) => entry.settings.name === selectedName) ?? null,
    [interfaces, selectedName],
  );

  // Land on the LAN: it is the interface a new box needs looked at first, and
  // the one whose settings are most often the reason for opening this page.
  useEffect(() => {
    if (network.data === null || selectedName !== null) {
      return;
    }
    const lan = network.data.interfaces.find(
      (entry) => entry.settings.role === "lan",
    );
    setSelectedName((lan ?? network.data.interfaces[0])?.settings.name ?? null);
  }, [network.data, selectedName]);

  // The tagged VLANs riding on the selected trunk, already applied on the
  // box. The untagged main is not in here: it exists exactly as long as the
  // split does, so it is never part of a draft.
  const appliedVlanIds = useMemo(
    () =>
      interfaces
        .map((entry) => entry.settings.vlan)
        .filter(
          (vlan): vlan is { parent: string; id: number } =>
            vlan !== null && vlan?.parent === selectedName && vlan.id !== null,
        )
        .map((vlan) => vlan.id),
    [interfaces, selectedName],
  );

  useEffect(() => {
    if (selected === null) {
      setDraft(null);
      return;
    }
    setDraft(structuredClone(selected.settings));
    setVlanIds(appliedVlanIds);
    setSaveError(null);
  }, [selected, appliedVlanIds]);

  const otherNetworks = useMemo<ServedNetwork[]>(
    () =>
      interfaces
        .filter(
          (entry) =>
            entry.settings.role === "lan" &&
            entry.settings.name !== selectedName &&
            entry.settings.lan.address.length > 0,
        )
        .map((entry) => ({
          name: entry.settings.name,
          address: entry.settings.lan.address,
          prefixLength: entry.settings.lan.prefix_len,
        })),
    [interfaces, selectedName],
  );

  const isWifi = selected?.link.kind === "wifi";
  const errors =
    draft === null ? {} : validateInterface(draft, { isWifi, otherNetworks });
  const isValid = isInterfaceDraftValid(errors);
  const isVlanDirty =
    draft?.role === "split" && !sameIdSet(vlanIds, appliedVlanIds);
  const isDirty =
    (draft !== null &&
      selected !== null &&
      JSON.stringify(draft) !== JSON.stringify(selected.settings)) ||
    isVlanDirty;

  const update = (patch: (current: InterfaceSettings) => void) => {
    setNotice(null);
    setDraft((current) => {
      if (current === null) {
        return current;
      }
      const next = structuredClone(current);
      patch(next);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (draft === null || selected === null || !isValid) {
      return;
    }

    // Leaving the split role takes every VLAN on the trunk with it.
    if (selected.settings.role === "split" && draft.role !== "split") {
      const children = interfaces
        .filter(
          (entry) => entry.settings.vlan?.parent === selected.settings.name,
        )
        .map((entry) => entry.settings.name);
      if (
        children.length > 0 &&
        !window.confirm(
          `Leaving the split role removes ${children.join(", ")}. Continue?`,
        )
      ) {
        return;
      }
    }

    // VLAN edits only mean something while the role stays split. Crossing off
    // a VLAN that already serves a network takes that network down.
    const vlanCreates =
      draft.role === "split"
        ? vlanIds.filter((id) => !appliedVlanIds.includes(id))
        : [];
    const vlanRemovals =
      draft.role === "split"
        ? interfaces.filter(
            (entry) =>
              entry.settings.vlan?.parent === draft.name &&
              entry.settings.vlan.id !== null &&
              !vlanIds.includes(entry.settings.vlan.id),
          )
        : [];
    const servingRemovals = vlanRemovals
      .filter((entry) => entry.settings.role !== "disabled")
      .map((entry) => entry.settings.name);
    if (
      servingRemovals.length > 0 &&
      !window.confirm(
        `Removing ${servingRemovals.join(", ")}: their networks stop existing. Continue?`,
      )
    ) {
      return;
    }

    // Rewriting the address of a LAN drops every session on it, including this
    // one. Say so before it happens, so the browser's network error afterwards
    // reads as expected rather than as a failure.
    const wasLan = selected.settings.role === "lan";
    const willBeLan = draft.role === "lan";
    const isAddressChanging =
      wasLan &&
      (!willBeLan ||
        draft.lan.address !== selected.settings.lan.address ||
        draft.lan.prefix_len !== selected.settings.lan.prefix_len ||
        draft.lan.upstream_gateway !== selected.settings.lan.upstream_gateway);
    if (isAddressChanging) {
      const destination = willBeLan
        ? `http://${draft.lan.address}`
        : "another interface";
      if (
        !window.confirm(
          `${selected.settings.name} is serving ${selected.link.ipv4_address ?? "the LAN"}. ` +
            `Changing it drops your connection to the panel — reopen it at ${destination} afterward. Continue?`,
        )
      ) {
        return;
      }
    }

    setIsSaving(true);
    setSaveError(null);
    setNotice(null);
    try {
      // The trunk goes first: a VLAN can only be created under a port that is
      // already split, and can only be removed while its entry still exists.
      let view = await apiPut<NetworkView>(
        `/network/interfaces/${draft.name}`,
        draft,
      );
      for (const id of vlanCreates) {
        view = await apiPut<NetworkView>(
          `/network/interfaces/${draft.name}.${id}`,
          newVlanSettings(draft.name, id),
        );
      }
      for (const entry of vlanRemovals) {
        view = await apiDelete<NetworkView>(
          `/network/interfaces/${entry.settings.name}`,
        );
      }
      network.setData(view);
      setNotice(
        isAddressChanging
          ? `Applied. Reopen the panel at ${willBeLan ? `http://${draft.lan.address}` : "its new address"}.`
          : `Applied to ${draft.name}.`,
      );
    } catch (cause: unknown) {
      setSaveError(describeError(cause));
      network.reload();
    } finally {
      setIsSaving(false);
    }
  };

  const isGlobalDirty =
    options !== null &&
    network.data !== null &&
    (options.is_ssh_from_wan_allowed !== network.data.is_ssh_from_wan_allowed ||
      options.uplink_policy !== network.data.uplink_policy ||
      options.is_inter_lan_allowed !== network.data.is_inter_lan_allowed);

  const applyOptions = async () => {
    if (options === null) {
      return;
    }
    setIsSavingOptions(true);
    setOptionsError(null);
    setOptionsNotice(null);
    try {
      const view = await apiPut<NetworkView>("/network/options", options);
      network.setData(view);
      setOptionsNotice("Applied to the whole gateway.");
    } catch (cause: unknown) {
      setOptionsError(describeError(cause));
    } finally {
      setIsSavingOptions(false);
    }
  };

  if (network.error !== null && network.data === null) {
    return (
      <div className="page">
        <h1>Network</h1>
        <ErrorPanel message={network.error} onRetry={network.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>Network</h1>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={() => {
              network.reload();
              deviceList.reload();
            }}
            disabled={network.isLoading}
          >
            <Icon name="refresh" size={13} />
            Refresh
          </button>
        </div>
      </div>

      <section className="settings_group network_topology">
        <div className="settings_group_title">
          <h2>Topology</h2>
        </div>
        {network.data === null ? (
          <div className="skeleton" style={{ height: 360 }} />
        ) : (
          <NetworkDiagram
            network={network.data}
            devices={deviceList.data?.devices ?? []}
            selectedName={selectedName}
            onSelect={setSelectedName}
          />
        )}
      </section>

      {(network.data?.warnings ?? []).map((warning) => (
        <div className="notice notice--warn" key={warning}>
          <Icon name="alert" size={15} />
          <div className="notice_body">{warning}</div>
        </div>
      ))}

      <div className="network_tabs" role="tablist" aria-label="Interfaces">
        {interfaces.map((entry) => (
          <InterfaceTab
            key={entry.settings.name}
            entry={entry}
            isSelected={entry.settings.name === selectedName}
            onSelect={() => setSelectedName(entry.settings.name)}
          />
        ))}
      </div>

      {selected !== null && draft !== null && (
        <section className={`card ${isDirty ? "card--dirty" : ""}`}>
          <LinkSummary entry={selected} />

          <div className="network_form">
            <div className="network_section">
              <span className="section_label">Role</span>
              <div className="network_roles">
                {ROLE_OPTIONS.filter(
                  (option) =>
                    option.value !== "split" ||
                    (!isWifi && draft.vlan === null),
                ).map((option) => {
                  // Serving a network over Wi-Fi needs access-point mode, and
                  // plenty of chipsets have none. Offering the role anyway
                  // would take an SSID, a passphrase and a save before failing,
                  // so it is refused up front and says why.
                  const isBlocked =
                    option.value === "lan" &&
                    isWifi &&
                    !selected.link.is_ap_capable;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      className={`network_role ${draft.role === option.value ? "network_role--on" : ""} ${isBlocked ? "network_role--blocked" : ""}`}
                      onClick={() =>
                        update((next) => (next.role = option.value))
                      }
                      aria-pressed={draft.role === option.value}
                      disabled={isBlocked}
                      title={
                        isBlocked
                          ? `${selected.settings.name} has no access-point mode`
                          : option.hint
                      }
                    >
                      <span className="network_role_label">
                        {isBlocked && (
                          <Icon
                            name="blocked"
                            size={13}
                            className="network_role_ban"
                          />
                        )}
                        {option.label}
                      </span>
                      <span className="network_role_hint">
                        {isBlocked
                          ? "No access-point mode on this card."
                          : option.hint}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {draft.role === "wan" && (
              <WanFields
                draft={draft}
                errors={errors}
                isWifi={isWifi}
                update={update}
                onJoined={network.setData}
              />
            )}
            {draft.role === "lan" && (
              <LanFields
                draft={draft}
                errors={errors}
                isWifi={isWifi}
                update={update}
                onJoined={network.setData}
              />
            )}
            {draft.role === "split" && (
              <VlanSection
                interfaces={interfaces}
                parentName={draft.name}
                ids={vlanIds}
                onChange={(ids) => {
                  setNotice(null);
                  setVlanIds(ids);
                }}
                onOpen={setSelectedName}
              />
            )}
            {draft.role === "disabled" && (
              <p className="field_hint">
                {draft.name} is unconfigured; nothing to set.
              </p>
            )}

            <ApplyBar
              isDirty={isDirty && isValid}
              isBusy={isSaving}
              label={`Apply to ${draft.name}`}
              hint={
                isValid
                  ? "Reconfigures this interface, then reloads the firewall and DHCP."
                  : "Fix the highlighted fields first."
              }
              error={saveError}
              notice={notice}
              onReset={() => {
                setDraft(structuredClone(selected.settings));
                setVlanIds(appliedVlanIds);
                setNotice(null);
                setSaveError(null);
              }}
              onApply={() => void handleSubmit()}
            />
          </div>
        </section>
      )}

      {network.data !== null && (
        <section className="network_globals">
          <div className="page_header_text">
            <h1>Global settings</h1>
          </div>
          {options !== null && (
            <section
              className={`settings_group ${isGlobalDirty ? "settings_group--dirty" : ""}`}
            >
              <ToggleSwitch
                isOn={options.uplink_policy === "balance"}
                onChange={(isOn) =>
                  setOptions({
                    ...options,
                    uplink_policy: isOn ? "balance" : "failover",
                  })
                }
                label="Spread traffic across uplinks"
                description="Off, one uplink carries everything and the rest wait. On, connections are shared across the separate upstream lines — two ports onto the same line still count as one, so this only does something with two real connections."
              />
              <ToggleSwitch
                isOn={options.is_inter_lan_allowed}
                onChange={(isOn) =>
                  setOptions({ ...options, is_inter_lan_allowed: isOn })
                }
                label="Networks reach each other"
                description="Off, devices on one of the gateway's networks cannot see devices on another; every network still reaches the internet and the overlay."
              />
              <ToggleSwitch
                isOn={options.is_ssh_from_wan_allowed}
                onChange={(isOn) =>
                  setOptions({ ...options, is_ssh_from_wan_allowed: isOn })
                }
                label="Allow SSH from the WAN"
                description="Whether port 22 answers on the uplink interfaces, reachable from the whole internet. Leave off once Tailscale is up; remote access does not need it."
              />
              <ApplyBar
                isDirty={isGlobalDirty}
                isBusy={isSavingOptions}
                label="Apply global settings"
                hint="Reloads the firewall and rebuilds the uplink routes."
                error={optionsError}
                notice={optionsNotice}
                onReset={() =>
                  setOptions({
                    is_ssh_from_wan_allowed:
                      network.data!.is_ssh_from_wan_allowed,
                    uplink_policy: network.data!.uplink_policy,
                    is_inter_lan_allowed: network.data!.is_inter_lan_allowed,
                  })
                }
                onApply={() => void applyOptions()}
              />
            </section>
          )}
        </section>
      )}
    </div>
  );
}

interface InterfaceTabProps {
  entry: InterfaceView;
  isSelected: boolean;
  onSelect: () => void;
}

function InterfaceTab({ entry, isSelected, onSelect }: InterfaceTabProps) {
  const { settings, link } = entry;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isSelected}
      className={`network_tab network_tab--${settings.role} ${isSelected ? "network_tab--on" : ""}`}
      onClick={onSelect}
    >
      <Icon name={link.kind === "wifi" ? "wifi" : "link"} size={14} />
      <span className="network_tab_name">{settings.name}</span>
      <span className="network_tab_role">{settings.role}</span>
      <StatusDot
        tone={
          settings.role === "disabled" ? "idle" : link.is_up ? "ok" : "error"
        }
      />
    </button>
  );
}

function LinkSummary({ entry }: { entry: InterfaceView }) {
  const { settings, link } = entry;
  const rows: [string, string][] = [
    [
      "Kind",
      settings.vlan === null
        ? link.kind
        : settings.vlan.id === null
          ? `untagged on ${settings.vlan.parent}`
          : `vlan ${settings.vlan.id} on ${settings.vlan.parent}`,
    ],
    ["Address", link.ipv4_address ?? "none"],
    ["MAC", link.mac_address ?? "unknown"],
    ["Connection", link.connection ?? "none"],
  ];
  if (settings.role === "wan") {
    rows.splice(2, 0, ["Gateway", link.gateway ?? "none"]);
  }
  return (
    <div className="network_link_summary">
      <div className="network_link_head">
        <h2 className="mono">{settings.name}</h2>
        <StatusDot
          tone={link.is_up ? "ok" : "error"}
          label={link.is_up ? "link up" : "link down"}
        />
        {link.ssid !== null && (
          <span className="badge badge--accent">{link.ssid}</span>
        )}
        {link.signal_percent !== null && (
          <SignalBars percent={link.signal_percent} isLabelled />
        )}
      </div>
      <dl className="network_link_rows">
        {rows.map(([key, value]) => (
          <div className="network_link_row" key={key}>
            <dt>{key}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface FieldsProps {
  draft: InterfaceSettings;
  errors: InterfaceErrors;
  isWifi: boolean;
  update: (patch: (current: InterfaceSettings) => void) => void;
  onJoined: (view: NetworkView) => void;
}

function WanFields({ draft, errors, isWifi, update, onJoined }: FieldsProps) {
  return (
    <>
      {isWifi && (
        <div className="network_section">
          <span className="section_label">Network to join</span>
          <WifiScanPanel
            interfaceName={draft.name}
            joinedSsid={draft.wifi.ssid.length > 0 ? draft.wifi.ssid : null}
            onJoined={onJoined}
          />
        </div>
      )}

      <div className="network_section">
        <span className="section_label">Priority</span>
        <p className="field_hint">
          The gateway ranks the uplinks itself, from which of them share one
          upstream line, which are wired, and what each negotiated. Say
          something here only where it would get that wrong.
        </p>
        <div className="network_choice_row">
          {INTENT_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`network_choice ${draft.wan.intent === option.value ? "network_choice--on" : ""}`}
              onClick={() => update((next) => (next.wan.intent = option.value))}
              aria-pressed={draft.wan.intent === option.value}
            >
              <strong>{option.label}</strong>
              <span>{option.hint}</span>
            </button>
          ))}
        </div>
      </div>

      {!isWifi && (
        <div className="network_section">
          <span className="section_label">Addressing</span>
          <div className="network_choice_row">
            <button
              type="button"
              className={`network_choice ${draft.wan.method === "dhcp" ? "network_choice--on" : ""}`}
              onClick={() => update((next) => (next.wan.method = "dhcp"))}
              aria-pressed={draft.wan.method === "dhcp"}
            >
              <strong>DHCP</strong>
              <span>Take an address from the upstream network.</span>
            </button>
            <button
              type="button"
              className={`network_choice ${draft.wan.method === "static" ? "network_choice--on" : ""}`}
              onClick={() => update((next) => (next.wan.method = "static"))}
              aria-pressed={draft.wan.method === "static"}
            >
              <strong>Static</strong>
              <span>Set the address and gateway by hand.</span>
            </button>
          </div>

          {draft.wan.method === "static" && (
            <div className="field_grid">
              <Field
                label="Address"
                value={draft.wan.address ?? ""}
                error={errors.wan_address}
                onChange={(value) =>
                  update((next) => (next.wan.address = value))
                }
              />
              <Field
                label="Prefix length"
                value={String(draft.wan.prefix_len)}
                error={errors.wan_prefix_len}
                onChange={(value) =>
                  update((next) => (next.wan.prefix_len = Number(value) || 0))
                }
              />
              <Field
                label="Gateway"
                value={draft.wan.gateway ?? ""}
                error={errors.wan_gateway}
                onChange={(value) =>
                  update((next) => (next.wan.gateway = value))
                }
              />
            </div>
          )}

          {(draft.vlan === null || draft.vlan.id === null) && (
            <Field
              label="Clone MAC"
              value={draft.wan.cloned_mac ?? ""}
              error={errors.wan_cloned_mac}
              hint="Leave blank to keep the hardware address."
              placeholder="aa:bb:cc:dd:ee:ff"
              onChange={(value) =>
                update(
                  (next) =>
                    (next.wan.cloned_mac = value.length > 0 ? value : null),
                )
              }
            />
          )}
        </div>
      )}
    </>
  );
}

function LanFields({ draft, errors, isWifi, update }: FieldsProps) {
  return (
    <>
      {isWifi && (
        <div className="network_section">
          <span className="section_label">Access point</span>
          <div className="field_grid">
            <Field
              label="Network name"
              value={draft.wifi.ap_ssid}
              error={errors.ap_ssid}
              onChange={(value) =>
                update((next) => (next.wifi.ap_ssid = value))
              }
            />
            <label className="field">
              <span className="field_label">Passphrase</span>
              <PasswordInput
                value={draft.wifi.ap_passphrase}
                onChange={(value) =>
                  update((next) => (next.wifi.ap_passphrase = value))
                }
                placeholder="8 to 63 characters"
              />
              {errors.ap_passphrase === undefined ? (
                <span className="field_hint">WPA2 only.</span>
              ) : (
                <span className="field_error">{errors.ap_passphrase}</span>
              )}
            </label>
            <label className="field">
              <span className="field_label">Band</span>
              <select
                className="select"
                value={draft.wifi.ap_band}
                onChange={(event) =>
                  update((next) => (next.wifi.ap_band = event.target.value))
                }
              >
                <option value="bg">2.4 GHz — further, slower</option>
                <option value="a">5 GHz — faster, shorter range</option>
              </select>
            </label>
          </div>
        </div>
      )}

      <div className="network_section">
        <span className="section_label">Addressing</span>
        <div className="field_grid">
          <Field
            label="Gateway address"
            value={draft.lan.address}
            error={errors.lan_address}
            hint="Clients get this as their gateway and resolver."
            onChange={(value) => update((next) => (next.lan.address = value))}
          />
          <Field
            label="Prefix length"
            value={String(draft.lan.prefix_len)}
            error={errors.lan_prefix_len}
            onChange={(value) =>
              update((next) => (next.lan.prefix_len = Number(value) || 0))
            }
          />
          {!isWifi && (
            <Field
              label="Upstream router"
              value={draft.lan.upstream_gateway ?? ""}
              error={errors.lan_upstream_gateway}
              hint="Blank normally; the existing network's router to run as a side gateway."
              placeholder="192.168.1.1"
              onChange={(value) =>
                update(
                  (next) =>
                    (next.lan.upstream_gateway =
                      value.trim().length > 0 ? value : null),
                )
              }
            />
          )}
        </div>
      </div>

      <div className="network_section">
        <span className="section_label">DHCP</span>
        <div className="network_toggles">
          <ToggleSwitch
            isOn={draft.lan.is_dhcp_enabled}
            onChange={(isOn) =>
              update((next) => (next.lan.is_dhcp_enabled = isOn))
            }
            label="Allocate address on this network"
            description="Off leaves clients to configure themselves; the gateway still answers DNS."
          />
        </div>
        {draft.lan.is_dhcp_enabled && (
          <div className="field_grid">
            <Field
              label="Range start"
              value={draft.lan.dhcp_range_start}
              error={errors.dhcp_range_start}
              onChange={(value) =>
                update((next) => (next.lan.dhcp_range_start = value))
              }
            />
            <Field
              label="Range end"
              value={draft.lan.dhcp_range_end}
              error={errors.dhcp_range_end}
              onChange={(value) =>
                update((next) => (next.lan.dhcp_range_end = value))
              }
            />
            <Field
              label="Lease time"
              value={draft.lan.dhcp_lease_time}
              error={errors.dhcp_lease_time}
              onChange={(value) =>
                update((next) => (next.lan.dhcp_lease_time = value))
              }
            />
          </div>
        )}
      </div>
    </>
  );
}

interface VlanSectionProps {
  interfaces: InterfaceView[];
  parentName: string;
  ids: number[];
  onChange: (ids: number[]) => void;
  onOpen: (name: string) => void;
}

function VlanSection({
  interfaces,
  parentName,
  ids,
  onChange,
  onOpen,
}: VlanSectionProps) {
  const [idText, setIdText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const children = interfaces.filter(
    (entry) => entry.settings.vlan?.parent === parentName,
  );
  const main =
    children.find((entry) => entry.settings.vlan?.id === null) ?? null;
  const childByVlanId = new Map(
    children
      .filter((entry) => entry.settings.vlan?.id !== null)
      .map((entry) => [entry.settings.vlan!.id, entry]),
  );

  const handleAdd = () => {
    const id = Number(idText.trim());
    if (!Number.isInteger(id) || id < VLAN_ID_MIN || id > VLAN_ID_MAX) {
      setError(`The VLAN id must be ${VLAN_ID_MIN} to ${VLAN_ID_MAX}.`);
      return;
    }
    if (ids.includes(id)) {
      setError(`VLAN ${id} is already on this trunk.`);
      return;
    }
    setError(null);
    setIdText("");
    onChange([...ids, id]);
  };

  return (
    <div className="network_section">
      <span className="section_label">VLANs</span>
      <p className="field_hint">
        Untagged traffic is the main interface; each VLAN rides tagged beside
        it.
      </p>

      <div className="network_vlan_rows">
        <div className="network_vlan_row" key="main">
          {main !== null ? (
            <button
              type="button"
              className="network_vlan_name mono"
              onClick={() => onOpen(main.settings.name)}
            >
              {main.settings.name}
            </button>
          ) : (
            <span className="network_vlan_name mono">{parentName}.main</span>
          )}
          <span className="badge">untagged</span>
          <span className="network_vlan_summary">
            {main !== null ? (
              describeVlanChild(main)
            ) : (
              <span className="badge badge--accent">created on apply</span>
            )}
          </span>
        </div>
        {ids.map((id) => {
          const child = childByVlanId.get(id);
          return (
            <div className="network_vlan_row" key={id}>
              {child !== undefined ? (
                <button
                  type="button"
                  className="network_vlan_name mono"
                  onClick={() => onOpen(child.settings.name)}
                >
                  {child.settings.name}
                </button>
              ) : (
                <span className="network_vlan_name mono">
                  {parentName}.{id}
                </span>
              )}
              <span className="badge">vlan {id}</span>
              <span className="network_vlan_summary">
                {child !== undefined ? (
                  describeVlanChild(child)
                ) : (
                  <span className="badge badge--accent">new on apply</span>
                )}
              </span>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => onChange(ids.filter((kept) => kept !== id))}
                aria-label={`Remove ${parentName}.${id}`}
              >
                <Icon name="close" size={13} />
              </button>
            </div>
          );
        })}
      </div>

      <div className="network_vlan_add">
        <input
          className="input network_vlan_id"
          value={idText}
          placeholder="vlan id"
          inputMode="numeric"
          onChange={(event) => {
            setIdText(event.target.value);
            setError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              handleAdd();
            }
          }}
        />
        <button
          type="button"
          className="button button--small"
          onClick={handleAdd}
          disabled={idText.trim().length === 0}
        >
          <Icon name="plus" size={13} />
          Add
        </button>
      </div>
      <p className="field_hint">
        Each VLAN becomes its own interface, configured from its tab once
        applied.
      </p>

      {error !== null && <span className="field_error">{error}</span>}
    </div>
  );
}

function sameIdSet(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((id) => b.includes(id));
}

function describeVlanChild(child: InterfaceView): string {
  const { settings } = child;
  if (settings.role === "wan") {
    return settings.wan.method === "static"
      ? `WAN ${settings.wan.address ?? ""}`
      : "WAN dhcp";
  }
  if (settings.role === "lan") {
    return `LAN ${settings.lan.address}/${settings.lan.prefix_len}`;
  }
  return "not configured yet";
}

interface FieldProps {
  label: string;
  value: string;
  error?: string;
  hint?: string;
  placeholder?: string;
  onChange: (value: string) => void;
}

function Field({
  label,
  value,
  error,
  hint,
  placeholder,
  onChange,
}: FieldProps) {
  return (
    <label className="field">
      <span className="field_label">{label}</span>
      <input
        className={`input ${error === undefined ? "" : "input--invalid"}`}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {error !== undefined ? (
        <span className="field_error">{error}</span>
      ) : (
        hint !== undefined && <span className="field_hint">{hint}</span>
      )}
    </label>
  );
}
