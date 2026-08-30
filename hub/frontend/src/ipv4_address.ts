/**
 * IPv4 parsing and subnet arithmetic for the network form.
 *
 * The panel validates before it lets the user submit, because applying a bad
 * LAN address restarts networking on a box whose only other way in is the WAN
 * side. Everything here is pure integer maths on the dotted-quad form.
 */

const OCTET_COUNT = 4;
const OCTET_MAX = 255;
const PREFIX_MAX = 32;

/** Whether a string is a well-formed dotted-quad IPv4 address. */
export function isIpv4Address(value: string): boolean {
  return parseIpv4(value) !== null;
}

/** Whether a prefix length is a usable IPv4 LAN prefix. */
export function isPrefixLength(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= PREFIX_MAX;
}

/**
 * Parse a dotted-quad address into its unsigned 32-bit value.
 *
 * Args:
 *   value: The candidate address, e.g. `192.168.100.1`.
 *
 * Returns:
 *   The numeric address, or null when the string is not a valid IPv4 address.
 *   Leading zeroes are rejected so `010.1.1.1` cannot be read two ways.
 */
export function parseIpv4(value: string): number | null {
  const parts = value.trim().split(".");
  if (parts.length !== OCTET_COUNT) {
    return null;
  }
  let result = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) {
      return null;
    }
    if (part.length > 1 && part.startsWith("0")) {
      return null;
    }
    const octet = Number(part);
    if (octet > OCTET_MAX) {
      return null;
    }
    result = result * 256 + octet;
  }
  return result >>> 0;
}

/**
 * Whether an address falls inside the subnet a base address and prefix define.
 *
 * Args:
 *   address: The address to test.
 *   networkAddress: Any address inside the target subnet, typically the LAN
 *     address of the gateway itself.
 *   prefixLength: The subnet prefix length in bits.
 *
 * Returns:
 *   True when both addresses share the same network portion.
 */
export function isInSubnet(
  address: string,
  networkAddress: string,
  prefixLength: number,
): boolean {
  const target = parseIpv4(address);
  const base = parseIpv4(networkAddress);
  if (target === null || base === null || !isPrefixLength(prefixLength)) {
    return false;
  }
  const mask = subnetMask(prefixLength);
  return (target & mask) >>> 0 === (base & mask) >>> 0;
}

/** Whether `start` sorts at or before `end` numerically. */
export function isOrderedRange(start: string, end: string): boolean {
  const first = parseIpv4(start);
  const last = parseIpv4(end);
  if (first === null || last === null) {
    return false;
  }
  return first <= last;
}

/** Render the CIDR form of an address and prefix, e.g. `192.168.100.1/24`. */
export function formatCidr(address: string, prefixLength: number): string {
  return `${address}/${prefixLength}`;
}

function subnetMask(prefixLength: number): number {
  if (prefixLength === 0) {
    return 0;
  }
  return (0xffffffff << (PREFIX_MAX - prefixLength)) >>> 0;
}
