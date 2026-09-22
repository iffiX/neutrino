import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { isInSubnet, isIpv4Address, parseIpv4 } from "../ipv4_address";
import { isMacAddress, normaliseMac } from "../mac_address";
import { useDraftSeeding } from "../use_draft_seeding";
import type {
  DeviceView,
  NetworkView,
  StaticLeaseSettings,
} from "../api_types";

import "./static_lease_panel.css";

/**
 * The devices that always get one address from a served network.
 *
 * One row per MAC, rendered as a dnsmasq `dhcp-host` line. The address lies
 * in a network that hands out leases and can sit inside its range, which
 * dnsmasq then keeps for that MAC; a device holding a dynamic lease moves at
 * its next renewal. Every row is checked here against the rules the hub
 * applies, so the bar stays dark on a row the hub would refuse.
 */

const MAC_LIST_ID = "static_lease_known_macs";
const HOSTNAME_PATTERN = /^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;
const PREFIX_MAX = 32;

interface StaticLeasePanelProps {
  /**
   * The page as the box holds it, never a draft: the write carries only the
   * rows, so an unapplied edit in another box is not written by this one.
   */
  network: NetworkView;
  /** The devices the hub knows, offered beside the MAC field. */
  devices: DeviceView[];
  onApplied: (view: NetworkView) => void;
}

/** A network dnsmasq hands out leases on, by the gateway's own address. */
interface LeasingNetwork {
  address: string;
  prefixLength: number;
}

type RowField = "mac_address" | "address" | "name";
type RowErrors = Partial<Record<RowField, string>>;

export function StaticLeasePanel({
  network,
  devices,
  onApplied,
}: StaticLeasePanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [rows, setRows] = useState<StaticLeaseSettings[]>(
    network.static_leases,
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The page polls, and a row typed but not applied stays until Apply or
  // Reset says otherwise.
  const isReseedable = useDraftSeeding(
    JSON.stringify(rows),
    JSON.stringify(network.static_leases),
  );
  useEffect(() => {
    if (!isReseedable(JSON.stringify(network.static_leases))) {
      return;
    }
    setRows(network.static_leases);
  }, [network.static_leases, isReseedable]);

  const leasing = leasingNetworks(network);
  const errors = rows.map((row, index) =>
    validateRow(row, index, rows, leasing),
  );
  const isValid = errors.every((entry) => Object.keys(entry).length === 0);
  const isDirty =
    JSON.stringify(rows) !== JSON.stringify(network.static_leases);

  const edit = (index: number, patch: Partial<StaticLeaseSettings>) => {
    setNotice(null);
    setRows(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)));
  };

  const add = () => {
    setNotice(null);
    setRows([...rows, { mac_address: "", address: "", name: "" }]);
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      const view = await apiPost<NetworkView>("/hub/network/set", {
        uplink_policy: network.uplink_policy,
        is_inter_lan_allowed: network.is_inter_lan_allowed,
        static_leases: rows,
      });
      onApplied(view);
      setNotice(t("ui.network.static_lease_applied"));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.network.static_lease_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.network.static_lease_hint")}</p>

      {rows.length === 0 && (
        <div className="placeholder">
          <span className="faint">{t("ui.network.static_lease_empty")}</span>
        </div>
      )}
      {rows.length > 0 && (
        <ul className="static_lease_rows">
          <li className="static_lease_row static_lease_row--head">
            <span className="field_label">
              {t("ui.network.static_lease_mac_label")}
            </span>
            <span className="field_label">
              {t("ui.network.static_lease_address_label")}
            </span>
            <span className="field_label">
              {t("ui.network.static_lease_name_label")}
            </span>
            <span />
          </li>
          {rows.map((row, index) => {
            const rowErrors = errors[index] ?? {};
            const rowError = firstError(rowErrors);
            return (
              <li className="static_lease_row" key={index}>
                <input
                  className={`input mono ${rowErrors.mac_address === undefined ? "" : "input--invalid"}`}
                  aria-label={t("ui.network.static_lease_mac_label")}
                  list={MAC_LIST_ID}
                  value={row.mac_address}
                  placeholder="aa:bb:cc:dd:ee:ff"
                  spellCheck={false}
                  onChange={(event) =>
                    edit(index, { mac_address: event.target.value })
                  }
                  onBlur={() =>
                    edit(index, { mac_address: normaliseMac(row.mac_address) })
                  }
                />
                <input
                  className={`input mono ${rowErrors.address === undefined ? "" : "input--invalid"}`}
                  aria-label={t("ui.network.static_lease_address_label")}
                  value={row.address}
                  placeholder={leasing[0]?.address ?? ""}
                  spellCheck={false}
                  onChange={(event) =>
                    edit(index, { address: event.target.value })
                  }
                />
                <input
                  className={`input ${rowErrors.name === undefined ? "" : "input--invalid"}`}
                  aria-label={t("ui.network.static_lease_name_label")}
                  value={row.name}
                  placeholder={t("ui.network.static_lease_name_placeholder")}
                  spellCheck={false}
                  onChange={(event) =>
                    edit(index, { name: event.target.value })
                  }
                />
                <button
                  type="button"
                  className="button button--ghost button--small"
                  aria-label={t("ui.network.static_lease_remove", {
                    mac_address: row.mac_address,
                  })}
                  onClick={() => {
                    setNotice(null);
                    setRows(rows.filter((_, at) => at !== index));
                  }}
                >
                  <Icon name="close" size={13} />
                </button>
                {rowError !== null && (
                  <span className="field_error static_lease_row_error">
                    {rowError}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <datalist id={MAC_LIST_ID}>
        {devices
          .filter((device) => device.link_mac.length > 0)
          .map((device) => (
            <option
              key={device.id}
              value={device.link_mac}
              label={deviceLabel(device)}
            />
          ))}
      </datalist>

      <div className="static_lease_add">
        <button
          type="button"
          className="button button--small"
          onClick={add}
          disabled={isBusy}
        >
          <Icon name="plus" size={13} />
          {t("ui.network.static_lease_add")}
        </button>
      </div>

      <ApplyBar
        isDirty={isDirty && isValid}
        isBusy={isBusy}
        label={t("ui.network.static_lease_apply")}
        hint={
          isValid
            ? t("ui.network.static_lease_apply_hint")
            : t("ui.network.fix_fields")
        }
        blockedHint={
          leasing.length === 0 ? t("ui.network.static_lease_blocked") : null
        }
        error={error}
        notice={notice}
        onReset={() => {
          setRows(network.static_leases);
          setError(null);
          setNotice(null);
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** The served networks whose DHCP is on and has a range. */
function leasingNetworks(network: NetworkView): LeasingNetwork[] {
  return network.interfaces
    .filter(
      (entry) =>
        entry.settings.role === "lan" &&
        entry.settings.lan.is_dhcp_enabled &&
        entry.settings.lan.dhcp_range_start.length > 0 &&
        entry.settings.lan.address.length > 0,
    )
    .map((entry) => ({
      address: entry.settings.lan.address,
      prefixLength: entry.settings.lan.prefix_len,
    }));
}

/** The same checks the hub makes, in the same order, one row at a time. */
function validateRow(
  row: StaticLeaseSettings,
  index: number,
  rows: StaticLeaseSettings[],
  leasing: LeasingNetwork[],
): RowErrors {
  const errors: RowErrors = {};
  const mac = normaliseMac(row.mac_address);
  if (!isMacAddress(row.mac_address)) {
    errors.mac_address = t("ui.network.error_mac");
  } else if (
    rows.some(
      (other, at) => at !== index && normaliseMac(other.mac_address) === mac,
    )
  ) {
    errors.mac_address = t("code.static_lease_duplicate", { value: mac });
  }

  const address = row.address.trim();
  if (!isIpv4Address(address)) {
    errors.address = t("ui.network.error_ipv4");
  } else {
    const holder = leasing.find((entry) =>
      isInSubnet(address, entry.address, entry.prefixLength),
    );
    if (holder === undefined) {
      errors.address = t("code.static_lease_outside", { address });
    } else if (isNetworkOrBroadcast(address, holder)) {
      errors.address = t("code.static_lease_address_invalid", { address });
    } else if (parseIpv4(address) === parseIpv4(holder.address)) {
      errors.address = t("code.static_lease_holds_gateway", { address });
    } else if (
      rows.some((other, at) => at !== index && other.address.trim() === address)
    ) {
      errors.address = t("code.static_lease_duplicate", { value: address });
    }
  }

  const name = row.name.trim();
  if (name.length > 0 && !HOSTNAME_PATTERN.test(name)) {
    errors.name = t("code.static_lease_name_invalid", { name });
  }
  return errors;
}

/** Whether an address is the network's own or its broadcast address. */
function isNetworkOrBroadcast(
  address: string,
  network: LeasingNetwork,
): boolean {
  const value = parseIpv4(address);
  const base = parseIpv4(network.address);
  if (value === null || base === null) {
    return false;
  }
  const hostBits = PREFIX_MAX - network.prefixLength;
  const mask = hostBits >= PREFIX_MAX ? 0 : (0xffffffff << hostBits) >>> 0;
  const networkAddress = (base & mask) >>> 0;
  const broadcastAddress = (networkAddress | (~mask >>> 0)) >>> 0;
  return value === networkAddress || value === broadcastAddress;
}

function firstError(errors: RowErrors): string | null {
  return errors.mac_address ?? errors.address ?? errors.name ?? null;
}

/** What a discovered device reads as in the MAC list. */
function deviceLabel(device: DeviceView): string {
  return [device.name, device.vendor, device.ipv4_address]
    .filter((part): part is string => part !== null && part.length > 0)
    .join(" · ");
}
