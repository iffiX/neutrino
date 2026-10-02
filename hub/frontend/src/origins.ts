/** This host's panel addresses on each scheme, with the scheme's own port left out. */

const HTTP_SCHEME_PORT = 80;
const HTTPS_SCHEME_PORT = 443;

export function httpOrigin(port: number): string {
  const suffix = port === HTTP_SCHEME_PORT ? "" : `:${port}`;
  return `http://${window.location.hostname}${suffix}`;
}

export function httpsOrigin(port: number): string {
  const suffix = port === HTTPS_SCHEME_PORT ? "" : `:${port}`;
  return `https://${window.location.hostname}${suffix}`;
}
