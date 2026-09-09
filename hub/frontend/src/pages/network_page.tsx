import { useEffect, useMemo, useRef, useState } from "react";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import type { IconName } from "../components/icon";
import { NetworkDiagram } from "../components/network_diagram";
import { NetworkExposurePanel } from "../components/network_exposure_panel";
import { NetworkModePanel } from "../components/network_mode_panel";
import { PanelPortPanel } from "../components/panel_port_panel";
import { PasswordInput } from "../components/password_input";
import { SavedNetworksPanel } from "../components/saved_networks_panel";
import { SignalBars } from "../components/signal_bars";
import { StatusDot } from "../components/status_dot";
import { TabStrip } from "../components/tab_strip";
import type { StripTab } from "../components/tab_strip";
import { ToggleSwitch } from "../components/toggle_switch";
import { UpstreamGatewayPanel } from "../components/upstream_gateway_panel";
import { WifiScanPanel } from "../components/wifi_scan_panel";
import { apiDelete, apiPut, describeError } from "../api_client";
import {
  isInterfaceDraftValid,
  validateInterface,
} from "../network_validation";
import { interruptionWarning } from "../network_warnings";
import type { InterfaceErrors, ServedNetwork } from "../network_validation";
import { useDraftSeeding } from "../use_draft_seeding";
import { useApiResource } from "../use_api_resource";
import {
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_LINKS,
} from "../use_hub_events";
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
 * What this machine is, and what each of its interfaces is doing.
 *
 * The mode comes first and everything below it follows from the answer. A
 * server has no uplink to rank and no network to hand out leases on, so it is
 * not shown a page shaped like a router's: it gets the two questions it
 * actually has — which interfaces answer, and on what port. The two router
 * modes get the wiring diagram, a tab per interface and a form for whichever
 * is selected.
 *
 * Each interface saves and applies on its own. Applying the whole page at once
 * would mean a mistake in the Wi-Fi settings could take the wired LAN down
 * with it, and the wired LAN is how you get back in.
 */

// What moves the diagram's device list: a machine's channel opening or
// ending, and one named, forgotten or enrolled.
const DEVICE_INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_DEVICE_REPORT },
];

// What moves the ports themselves: a cable pulled out, a lease renewed or a
// radio losing signal, which the hub samples and says; and any write to the
// router's own configuration.
const NETWORK_INVALIDATE_ON = [
  { type: HUB_EVENT_LINKS },
  { type: HUB_EVENT_CONFIG },
];

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

// What each kind of port is drawn as. A modem is the way out of a building
// with no wire into it, so it is drawn as the world rather than as a cable.
const LINK_ICONS: Record<string, IconName> = {
  wifi: "wifi",
  modem: "globe",
  // A tag on a trunk, drawn as the switch it rides through. Not the world:
  // that glyph is the modem's here and the proxy's everywhere else, and two
  // rows of the same picture is a row nobody reads.
  vlan: "network",
  ethernet: "link",
};

// Which accent a role's pill wears. The two that carry traffic are told apart
// by colour; the rest read in the tab's own tone.
const ROLE_TAG_TONES: Record<string, "accent" | "secondary"> = {
  wan: "secondary",
  lan: "accent",
};

const VLAN_ID_MIN = 1;
const VLAN_ID_MAX = 4094;

/** A fresh VLAN interface, born disabled so adding it changes nothing yet. */
function newVlanSettings(parent: string, id: number): InterfaceSettings {
  return {
    name: `${parent}.${id}`,
    role: "disabled",
    // Sent and discarded: which interfaces answer is written as a set by the
    // panel that shows all of them, not by a request about one of them.
    is_exposed: false,
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

/** Everything the interface form stages: the settings and the VLANs beside them. */
function interfacePayload(
  settings: InterfaceSettings,
  vlanIds: number[],
): string {
  return JSON.stringify([settings, [...vlanIds].sort((a, b) => a - b)]);
}

export function NetworkPage() {
  const network = useApiResource<NetworkView>("/network", {
    invalidateOn: NETWORK_INVALIDATE_ON,
  });
  // The cheap list endpoint, no ARP sweep: the diagram only wants to draw
  // what is already known, and it draws what is there now rather than what
  // was there when the page opened.
  const deviceList = useApiResource<DevicesResponse>("/devices", {
    invalidateOn: DEVICE_INVALIDATE_ON,
  });

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

  // Both forms on this page against what the box holds. The page polls, so
  // every panel below has to answer whether a payload landing under it may
  // take the form over, and each answers for itself.
  const isInterfaceReseedable = useDraftSeeding(
    draft === null ? null : interfacePayload(draft, vlanIds),
    selected === null
      ? null
      : interfacePayload(selected.settings, appliedVlanIds),
  );
  const isOptionsReseedable = useDraftSeeding(
    options === null ? null : JSON.stringify(options),
    network.data === null ? null : JSON.stringify(optionsOf(network.data)),
  );
  // Which interface the form was last seeded for. Picking another one always
  // reseeds: the form then belongs to a different port.
  const seededNameRef = useRef<string | null>(null);

  useEffect(() => {
    if (network.data === null) {
      return;
    }
    const fresh = optionsOf(network.data);
    if (!isOptionsReseedable(JSON.stringify(fresh))) {
      return;
    }
    setOptions(fresh);
  }, [network.data, isOptionsReseedable]);

  // The form follows the box while nothing has been typed into it, and stops
  // following the moment something has: a tick landing under a half-entered
  // address must not take it away.
  useEffect(() => {
    if (selected === null) {
      seededNameRef.current = null;
      setDraft(null);
      return;
    }
    const isSameInterface = seededNameRef.current === selected.settings.name;
    const fresh = interfacePayload(selected.settings, appliedVlanIds);
    if (isSameInterface && !isInterfaceReseedable(fresh)) {
      return;
    }
    seededNameRef.current = selected.settings.name;
    setDraft(structuredClone(selected.settings));
    setVlanIds(appliedVlanIds);
    setSaveError(null);
  }, [selected, appliedVlanIds, isInterfaceReseedable]);

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

  // Which sections there are at all. The two router modes are the only ones
  // with a wiring diagram, uplinks to rank or networks to serve.
  const isRouting = network.data?.mode === "router";
  const isWifi = selected?.link.kind === "wifi";
  // A carrier hands a modem one address on a point-to-point link: there is
  // nothing to serve a network on, and nothing to carry a VLAN tag.
  const isModem = selected?.link.kind === "modem";
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

  // Joining a network is written at once rather than staged, so the view it
  // answers with owns the form: the interface it names is the one whose SSID
  // just changed.
  const handleJoined = (view: NetworkView) => {
    seededNameRef.current = null;
    network.setData(view);
  };

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

  // What applying this interface costs, in the shape every warning on this
  // page takes: what changes, then what it interrupts.
  const warning = interfaceWarning({ selected, draft, interfaces, vlanIds });

  const handleSubmit = async () => {
    if (draft === null || selected === null || !isValid) {
      return;
    }

    // VLAN edits only mean something while the role stays split. Crossing off
    // a VLAN takes the network it serves down with it.
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
    const willBeLan = draft.role === "lan";
    const isAddressChanging = isServedAddressChanging(selected, draft);

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
    (options.uplink_policy !== network.data.uplink_policy ||
      options.is_inter_lan_allowed !== network.data.is_inter_lan_allowed);

  const applyOptions = async () => {
    if (options === null) {
      return;
    }
    setIsSavingOptions(true);
    setOptionsError(null);
    setOptionsNotice(null);
    try {
      const view = await apiPut<NetworkView>("/network", options);
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
        <div className="page_title_row">
          <h1>Network</h1>
        </div>
      </div>

      {network.data === null ? (
        <div className="skeleton" style={{ height: 220 }} />
      ) : (
        <NetworkModePanel network={network.data} onApplied={network.setData} />
      )}

      {network.data !== null && network.data.mode === "side_gateway" && (
        <UpstreamGatewayPanel
          network={network.data}
          onApplied={network.setData}
        />
      )}

      {isRouting && network.data !== null && (
        <section className="settings_group network_topology">
          <div className="settings_group_title">
            <h2>Topology</h2>
          </div>
          <NetworkDiagram
            network={network.data}
            devices={deviceList.data?.devices ?? []}
            selectedName={selectedName}
            onSelect={setSelectedName}
          />
        </section>
      )}

      {isRouting &&
        (network.data?.warnings ?? []).map((warning) => (
          <div className="notice notice--warn" key={warning}>
            <Icon name="alert" size={15} />
            <div className="notice_body">{warning}</div>
          </div>
        ))}

      {isRouting && (
        <TabStrip
          label="Interfaces"
          tabs={interfaces.map(toInterfaceTab)}
          selected={selectedName}
          onSelect={setSelectedName}
        />
      )}

      {isRouting && (
        <>
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
                        (!isWifi && !isModem && draft.vlan === null),
                    ).map((option) => {
                      // Serving a network needs somewhere to serve it: an
                      // access-point mode plenty of Wi-Fi chipsets have none of,
                      // or a wire. Offering the role anyway would take an SSID,
                      // a passphrase and a save before failing, so it is refused
                      // up front and says why.
                      const isBlocked =
                        option.value === "lan" && !selected.link.is_ap_capable;
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
                              ? isModem
                                ? `${selected.settings.name} is a modem: the carrier gives it one address and nothing to serve`
                                : `${selected.settings.name} has no access-point mode`
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
                    onJoined={handleJoined}
                  />
                )}
                {draft.role === "lan" && (
                  <LanFields
                    draft={draft}
                    errors={errors}
                    isWifi={isWifi}
                    update={update}
                    onJoined={handleJoined}
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
                  warning={warning}
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
              {/* Only where there is a radio to use them. On a box with none
                  this is a list nothing would ever read. */}
              {interfaces.some((entry) => entry.link.kind === "wifi") && (
                <SavedNetworksPanel />
              )}
              {options !== null && (
                <section
                  className={`settings_group ${isGlobalDirty ? "settings_group--dirty" : ""}`}
                >
                  <div className="settings_group_title">
                    <h2>Routing behavior</h2>
                  </div>
                  <ToggleSwitch
                    isOn={options.uplink_policy === "balance"}
                    onChange={(isOn) =>
                      setOptions({
                        ...options,
                        uplink_policy: isOn ? "balance" : "failover",
                      })
                    }
                    label="Spread traffic across uplinks"
                    description="Whether connections are spread across the separate upstream lines. Two ports onto one line still count as one, so this only does something with two real connections."
                  />
                  <ToggleSwitch
                    isOn={options.is_inter_lan_allowed}
                    onChange={(isOn) =>
                      setOptions({ ...options, is_inter_lan_allowed: isOn })
                    }
                    label="Networks reach each other"
                    description="Whether devices on one of the gateway's networks can reach devices on another. Every network reaches the internet and the overlay either way."
                  />
                  <ApplyBar
                    isDirty={isGlobalDirty}
                    isBusy={isSavingOptions}
                    label="Apply routing behavior"
                    hint="Reloads the firewall and rebuilds the uplink routes."
                    error={optionsError}
                    notice={optionsNotice}
                    onReset={() => setOptions(optionsOf(network.data!))}
                    onApply={() => void applyOptions()}
                  />
                </section>
              )}
            </section>
          )}
        </>
      )}

      {network.data !== null && (
        <NetworkExposurePanel
          network={network.data}
          onApplied={network.setData}
        />
      )}

      <PanelPortPanel />
    </div>
  );
}

/** Whether applying moves the address of a network this box already serves. */
function isServedAddressChanging(
  selected: InterfaceView | null,
  draft: InterfaceSettings | null,
): boolean {
  if (selected === null || draft === null || selected.settings.role !== "lan") {
    return false;
  }
  return (
    draft.role !== "lan" ||
    draft.lan.address !== selected.settings.lan.address ||
    draft.lan.prefix_len !== selected.settings.lan.prefix_len ||
    draft.lan.upstream_gateway !== selected.settings.lan.upstream_gateway
  );
}

interface InterfaceWarningInput {
  selected: InterfaceView | null;
  draft: InterfaceSettings | null;
  interfaces: InterfaceView[];
  vlanIds: number[];
}

/**
 * What applying this interface costs, or undefined when it costs nothing.
 *
 * One warning and never two, in the shape the whole page uses: the mechanism,
 * then the interruption. What the change *is* belongs to the fields above it
 * and to the bar's own hint.
 */
function interfaceWarning({
  selected,
  draft,
  interfaces,
  vlanIds,
}: InterfaceWarningInput): string | undefined {
  if (selected === null || draft === null) {
    return undefined;
  }
  const dropped =
    draft.role === "split"
      ? interfaces
          .filter(
            (entry) =>
              entry.settings.vlan?.parent === draft.name &&
              entry.settings.vlan.id !== null &&
              !vlanIds.includes(entry.settings.vlan.id),
          )
          .map((entry) => entry.settings.name)
      : interfaces
          .filter((entry) => entry.settings.vlan?.parent === draft.name)
          .map((entry) => entry.settings.name);
  return interruptionWarning(
    dropped.length === 0
      ? null
      : `${dropped.join(", ")} and the networks they serve are removed.`,
    isServedAddressChanging(selected, draft)
      ? `The address ${selected.settings.name} serves is reassigned and its ` +
          "leases are reissued."
      : null,
  );
}

/** The module's own settings, as the box holds them now. */
function optionsOf(view: NetworkView): NetworkOptions {
  return {
    uplink_policy: view.uplink_policy,
    is_inter_lan_allowed: view.is_inter_lan_allowed,
    exposed_interfaces: view.interfaces
      .filter((entry) => entry.settings.is_exposed)
      .map((entry) => entry.settings.name),
    exposed_overlays: view.overlays
      .filter((overlay) => overlay.is_exposed)
      .map((overlay) => overlay.provider),
  };
}

/** One interface as the tab strip wants it. */
function toInterfaceTab(entry: InterfaceView): StripTab {
  const { settings, link } = entry;
  return {
    key: settings.name,
    icon: LINK_ICONS[link.kind] ?? "link",
    name: settings.name,
    tag: settings.role,
    tagTone: ROLE_TAG_TONES[settings.role],
    dotTone:
      settings.role === "disabled" ? "idle" : link.is_up ? "ok" : "error",
  };
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
            description="Whether this network hands out addresses. The gateway answers DNS on it either way."
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
