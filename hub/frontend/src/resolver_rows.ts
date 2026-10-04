/**
 * One resolver as a row of a list editor, and back.
 *
 * A row is an address, or `<address>:<port>`, an IPv6 address in brackets
 * when it has a port. A row naming no port is port 53. What the address
 * means is the backend's to check; a row it cannot read as an address and a
 * port goes over whole as the address, and the refusal names it.
 */

import type { DnsServer } from "./api_types";

const RESOLVER_DEFAULT_PORT = 53;
const BRACKETED_ROW = /^\[([^\]]+)\](?::(\d+))?$/;
const PLAIN_ROW = /^([^:]+):(\d+)$/;

/** A resolver as the row the list shows. */
export function resolverRow(server: DnsServer): string {
  if (server.port === RESOLVER_DEFAULT_PORT) {
    return server.address;
  }
  const address = server.address.includes(":")
    ? `[${server.address}]`
    : server.address;
  return `${address}:${server.port}`;
}

/** A row the person typed as the resolver the backend takes. */
export function resolverOf(row: string): DnsServer {
  const text = row.trim();
  const [, bracketed, bracketedPort] = BRACKETED_ROW.exec(text) ?? [];
  if (bracketed !== undefined) {
    return {
      address: bracketed,
      port:
        bracketedPort === undefined
          ? RESOLVER_DEFAULT_PORT
          : Number(bracketedPort),
    };
  }
  const [, plain, plainPort] = PLAIN_ROW.exec(text) ?? [];
  if (plain !== undefined && plainPort !== undefined) {
    return { address: plain, port: Number(plainPort) };
  }
  return { address: text, port: RESOLVER_DEFAULT_PORT };
}

/**
 * The rows of a list as resolvers, in order, each once.
 *
 * `1.1.1.1` and `1.1.1.1:53` are one resolver, which the editor's own check
 * on the typed text does not see.
 */
export function resolversOf(rows: string[]): DnsServer[] {
  const servers: DnsServer[] = [];
  for (const row of rows) {
    const server = resolverOf(row);
    const isKnown = servers.some(
      (known) => known.address === server.address && known.port === server.port,
    );
    if (!isKnown) {
      servers.push(server);
    }
  }
  return servers;
}
