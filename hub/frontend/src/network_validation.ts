import {
  isInSubnet,
  isIpv4Address,
  isOrderedRange,
  isPrefixLength,
} from "./ipv4_address";
import { isMacAddress } from "./mac_address";
import type { InterfaceSettings } from "./api_types";

/**
 * Field-level validation for one interface's settings.
 *
 * Saving applies immediately, and on the LAN that means rewriting the address
 * the panel is being reached on. A typo there cuts the only wired path back to
 * the box, so everything is checked in the browser first; the backend checks
 * the same things again, because a panel is not the only thing that can PUT.
 *
 * Only the fields of the interface's *current* role are checked. The other
 * blocks are kept so switching roles does not lose them, but half-filled
 * settings for a role the interface does not have must not block a save.
 */

const LEASE_TIME_PATTERN = /^\d+[smhd]$|^infinite$/i;

/** WPA2's own limits; an access point with no passphrase is not offered. */
export const AP_PASSPHRASE_MIN_LENGTH = 8;
export const AP_PASSPHRASE_MAX_LENGTH = 63;

export type InterfaceFieldName =
  | "lan_address"
  | "lan_prefix_len"
  | "lan_upstream_gateway"
  | "dhcp_range_start"
  | "dhcp_range_end"
  | "dhcp_lease_time"
  | "wan_address"
  | "wan_prefix_len"
  | "wan_gateway"
  | "wan_cloned_mac"
  | "ap_ssid"
  | "ap_passphrase";

export type InterfaceErrors = Partial<Record<InterfaceFieldName, string>>;

/** One other interface's network, for the overlap check. */
export interface ServedNetwork {
  name: string;
  address: string;
  prefixLength: number;
}

interface ValidationContext {
  isWifi: boolean;
  otherNetworks: ServedNetwork[];
}

/**
 * Validate one interface's draft settings.
 *
 * Args:
 *   draft: The form state.
 *   context: Whether the interface is wireless, and the networks the box's
 *     other interfaces already serve.
 *
 * Returns:
 *   A map from field name to the first problem found with it. An empty map
 *   means the draft is safe to submit.
 */
export function validateInterface(
  draft: InterfaceSettings,
  context: ValidationContext,
): InterfaceErrors {
  if (draft.role === "lan") {
    return validateLan(draft, context);
  }
  if (draft.role === "wan") {
    return validateWan(draft);
  }
  return {};
}

/** Whether a validation result allows the form to be submitted. */
export function isInterfaceDraftValid(errors: InterfaceErrors): boolean {
  return Object.keys(errors).length === 0;
}

function validateLan(
  draft: InterfaceSettings,
  { isWifi, otherNetworks }: ValidationContext,
): InterfaceErrors {
  const errors: InterfaceErrors = {};
  const { lan } = draft;

  if (!isIpv4Address(lan.address)) {
    errors.lan_address = "Enter a valid IPv4 address, e.g. 192.168.100.1";
  }
  if (!isPrefixLength(lan.prefix_len)) {
    errors.lan_prefix_len = "Prefix length must be between 1 and 32.";
  }

  const isSubnetUsable =
    errors.lan_address === undefined && errors.lan_prefix_len === undefined;

  if (isSubnetUsable) {
    // Two networks that overlap leave clients on either with an ambiguous
    // route, and dnsmasq handing out leases from whichever pool matched first.
    const clash = otherNetworks.find(
      (other) =>
        isInSubnet(other.address, lan.address, lan.prefix_len) ||
        isInSubnet(lan.address, other.address, other.prefixLength),
    );
    if (clash !== undefined) {
      errors.lan_address = `Overlaps the network ${clash.name} serves (${clash.address}/${clash.prefixLength}).`;
    }
  }

  const upstream = lan.upstream_gateway ?? "";
  if (upstream.trim().length > 0) {
    if (!isIpv4Address(upstream)) {
      errors.lan_upstream_gateway = "Enter a valid IPv4 address.";
    } else if (
      isSubnetUsable &&
      !isInSubnet(upstream, lan.address, lan.prefix_len)
    ) {
      errors.lan_upstream_gateway = "Must sit inside this network.";
    } else if (upstream === lan.address) {
      errors.lan_upstream_gateway =
        "That is the gateway's own address; name the network's real router.";
    }
  }

  if (lan.is_dhcp_enabled) {
    if (!isIpv4Address(lan.dhcp_range_start)) {
      errors.dhcp_range_start = "Enter a valid IPv4 address.";
    } else if (
      isSubnetUsable &&
      !isInSubnet(lan.dhcp_range_start, lan.address, lan.prefix_len)
    ) {
      errors.dhcp_range_start = "Must sit inside this network.";
    }

    if (!isIpv4Address(lan.dhcp_range_end)) {
      errors.dhcp_range_end = "Enter a valid IPv4 address.";
    } else if (
      isSubnetUsable &&
      !isInSubnet(lan.dhcp_range_end, lan.address, lan.prefix_len)
    ) {
      errors.dhcp_range_end = "Must sit inside this network.";
    } else if (
      errors.dhcp_range_start === undefined &&
      !isOrderedRange(lan.dhcp_range_start, lan.dhcp_range_end)
    ) {
      errors.dhcp_range_end =
        "The end of the range must not precede its start.";
    }

    if (
      errors.dhcp_range_start === undefined &&
      errors.dhcp_range_end === undefined &&
      isSubnetUsable &&
      isOrderedRange(lan.dhcp_range_start, lan.address) &&
      isOrderedRange(lan.address, lan.dhcp_range_end)
    ) {
      errors.lan_address = "The gateway address must lie outside the pool.";
    }

    if (!LEASE_TIME_PATTERN.test(lan.dhcp_lease_time.trim())) {
      errors.dhcp_lease_time = "Use a dnsmasq duration such as 12h, 30m or 1d.";
    }
  }

  if (isWifi) {
    if (draft.wifi.ap_ssid.trim().length === 0) {
      errors.ap_ssid = "Name the network this interface will publish.";
    }
    const length = draft.wifi.ap_passphrase.length;
    if (
      length < AP_PASSPHRASE_MIN_LENGTH ||
      length > AP_PASSPHRASE_MAX_LENGTH
    ) {
      errors.ap_passphrase = `WPA2 needs ${AP_PASSPHRASE_MIN_LENGTH} to ${AP_PASSPHRASE_MAX_LENGTH} characters.`;
    }
  }

  return errors;
}

function validateWan(draft: InterfaceSettings): InterfaceErrors {
  const errors: InterfaceErrors = {};
  const { wan } = draft;

  if (wan.method === "static") {
    if (!isIpv4Address(wan.address ?? "")) {
      errors.wan_address = "Enter a valid IPv4 address.";
    }
    if (!isPrefixLength(wan.prefix_len)) {
      errors.wan_prefix_len = "Prefix length must be between 1 and 32.";
    }
    if (!isIpv4Address(wan.gateway ?? "")) {
      errors.wan_gateway = "A static uplink needs a gateway address.";
    } else if (
      errors.wan_address === undefined &&
      errors.wan_prefix_len === undefined &&
      !isInSubnet(wan.gateway ?? "", wan.address ?? "", wan.prefix_len)
    ) {
      errors.wan_gateway = "The gateway must sit inside this subnet.";
    }
  }

  if (
    wan.cloned_mac !== null &&
    wan.cloned_mac.trim().length > 0 &&
    !isMacAddress(wan.cloned_mac)
  ) {
    errors.wan_cloned_mac = "Enter a MAC such as aa:bb:cc:dd:ee:ff.";
  }

  return errors;
}
