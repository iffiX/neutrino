import type { ReactNode } from "react";

/**
 * The panel's icon set, drawn inline so the appliance needs no icon font and
 * no network fetch to render its own control panel.
 *
 * Every glyph is a 24x24 stroke drawing that inherits `currentColor`, which is
 * what lets a badge, a button and a nav item tint the same icon differently
 * without a second asset.
 */

export type IconName =
  | "dashboard"
  | "nodes"
  | "network"
  | "proxy"
  | "mesh"
  | "globe"
  | "devices"
  | "services"
  | "settings"
  | "power"
  | "refresh"
  | "terminal"
  | "download"
  | "upload"
  | "folder"
  | "file"
  | "sparkles"
  | "trash"
  | "plus"
  | "close"
  | "check"
  | "alert"
  | "bolt"
  | "play"
  | "stop"
  | "chevron_down"
  | "chevron_right"
  | "search"
  | "logout"
  | "lock"
  | "eye"
  | "eye_off"
  | "wifi"
  | "blocked"
  | "arrow_up"
  | "arrow_down"
  | "cpu"
  | "memory"
  | "clock"
  | "link"
  | "key"
  | "edit"
  | "laptop"
  | "desktop"
  | "phone"
  | "tablet"
  | "tv"
  | "printer"
  | "server"
  | "nas"
  | "camera"
  | "router"
  | "gitea"
  | "cube"
  | "hard_drive"
  | "database"
  | "unknown";

const ICON_SHAPES: Record<IconName, ReactNode> = {
  dashboard: <path d="M3 12h4l3 8 4-16 3 8h4" />,
  nodes: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c2.5 2.4 3.8 5.5 3.8 9S14.5 18.6 12 21c-2.5-2.4-3.8-5.5-3.8-9S9.5 5.4 12 3z" />
    </>
  ),
  network: (
    <>
      <rect x="2" y="13" width="20" height="8" rx="2" />
      <path d="M6 17h.01M10 17h.01" />
      <path d="M12 9V3" />
      <path d="m8.5 6.5 3.5-3.5 3.5 3.5" />
    </>
  ),
  proxy: <path d="m12 3 8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6z" />,
  // An overlay: peers meeting at one point over whatever is underneath. It
  // has to read as none of its neighbours — the globe is the proxy's, the
  // chain is a wired interface's — because they sit in the same row.
  mesh: (
    <>
      <circle cx="12" cy="12" r="2.4" />
      <circle cx="5" cy="5.5" r="1.9" />
      <circle cx="19" cy="5.5" r="1.9" />
      <circle cx="12" cy="20" r="1.9" />
      <path d="M10.3 10.3 6.4 6.9M13.7 10.3l3.9-3.4M12 14.4v3.7" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c2.6 2.5 3.9 5.5 3.9 9s-1.3 6.5-3.9 9c-2.6-2.5-3.9-5.5-3.9-9S9.4 5.5 12 3z" />
    </>
  ),
  devices: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  services: (
    <>
      <path d="m12 2 9 5-9 5-9-5z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 17 9 5 9-5" />
    </>
  ),
  settings: (
    <>
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
      <path d="M1 14h6M9 8h6M17 16h6" />
    </>
  ),
  power: (
    <>
      <path d="M12 3v9" />
      <path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
    </>
  ),
  refresh: (
    <>
      <path d="M21 12a9 9 0 1 1-2.6-6.4" />
      <path d="M21 3v6h-6" />
    </>
  ),
  terminal: (
    <>
      <path d="m4 17 6-5-6-5" />
      <path d="M12 19h8" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M4 21h16" />
    </>
  ),
  upload: (
    <>
      <path d="M12 20V8" />
      <path d="m7 13 5-5 5 5" />
      <path d="M4 4h16" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M10 11v6M14 11v6" />
      <path d="m6 7 1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
      <path d="M9 7V4h6v3" />
    </>
  ),
  folder: (
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  ),
  sparkles: (
    <>
      <path d="m10 4 1.7 4.3L16 10l-4.3 1.7L10 16l-1.7-4.3L4 10l4.3-1.7z" />
      <path d="m18 13 .9 2.1 2.1.9-2.1.9L18 19l-.9-2.1-2.1-.9 2.1-.9z" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  check: <path d="m4 13 5 5L20 6" />,
  alert: (
    <>
      <path d="M12 3 2 20h20z" />
      <path d="M12 10v5" />
      <path d="M12 18h.01" />
    </>
  ),
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  play: <path d="m6 4 14 8-14 8z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  chevron_down: <path d="m6 9 6 6 6-6" />,
  chevron_right: <path d="m9 6 6 6-6 6" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  logout: (
    <>
      <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
      <path d="m10 17 5-5-5-5" />
      <path d="M15 12H3" />
    </>
  ),
  lock: (
    <>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  eye_off: (
    <>
      <path d="M10.7 6.2A9.7 9.7 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3 3.6M6.3 6.3A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 4-.9" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="M2 2l20 20" />
    </>
  ),
  wifi: (
    <>
      <path d="M2 8.5a16 16 0 0 1 20 0" />
      <path d="M5 12.5a11 11 0 0 1 14 0" />
      <path d="M8.5 16.2a6 6 0 0 1 7 0" />
      <path d="M12 20h.01" />
    </>
  ),
  blocked: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.6 5.6 12.8 12.8" />
    </>
  ),
  arrow_up: (
    <>
      <path d="M12 20V5" />
      <path d="m6 11 6-6 6 6" />
    </>
  ),
  arrow_down: (
    <>
      <path d="M12 4v15" />
      <path d="m6 13 6 6 6-6" />
    </>
  ),
  cpu: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3" />
    </>
  ),
  memory: (
    <>
      <rect x="3" y="7" width="18" height="10" rx="2" />
      <path d="M7 17v3M12 17v3M17 17v3" />
      <path d="M8 11v2M12 11v2M16 11v2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="15" r="4" />
      <path d="m11 12 9-9" />
      <path d="m17 6 2 2" />
      <path d="m14 9 2 2" />
    </>
  ),
  edit: (
    <>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </>
  ),
  laptop: (
    <>
      <rect x="4" y="5" width="16" height="11" rx="2" />
      <path d="M2 20h20" />
    </>
  ),
  desktop: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M9 20h6" />
      <path d="M12 16v4" />
    </>
  ),
  phone: (
    <>
      <rect x="7" y="2" width="10" height="20" rx="2.5" />
      <path d="M11 18h2" />
    </>
  ),
  tablet: (
    <>
      <rect x="5" y="2" width="14" height="20" rx="2.5" />
      <path d="M11 18h2" />
    </>
  ),
  tv: (
    <>
      <rect x="2" y="5" width="20" height="13" rx="2" />
      <path d="m8 21 4-3 4 3" />
    </>
  ),
  printer: (
    <>
      <path d="M6 9V3h12v6" />
      <rect x="3" y="9" width="18" height="8" rx="2" />
      <path d="M6 15h12v6H6z" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="3" width="18" height="7" rx="2" />
      <rect x="3" y="14" width="18" height="7" rx="2" />
      <path d="M7 6.5h.01M7 17.5h.01" />
    </>
  ),
  nas: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 7h8M8 12h8M8 17h4" />
    </>
  ),
  // Gitea's tea cup, reduced to strokes: body, handle, and the steam.
  gitea: (
    <>
      <path d="M4.5 8.5h11v5.5a5.5 5.5 0 0 1-11 0V8.5z" />
      <path d="M15.5 9.5h1.5a3 3 0 0 1 0 6h-1.7" />
      <path d="M8 5.5V4M11.5 5.5V3.5" />
    </>
  ),
  // A shipping cube, the container that is not the Services stack.
  cube: (
    <>
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="M3.3 7 12 12l8.7-5M12 22V12" />
    </>
  ),
  // A disk with its activity lights, for storage that is a place, not a rack.
  hard_drive: (
    <>
      <path d="M22 12H2" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      <path d="M6 16h.01M10 16h.01" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" />
      <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
    </>
  ),
  camera: (
    <>
      <path d="M3 8h4l2-3h6l2 3h4v11H3z" />
      <circle cx="12" cy="13" r="3.5" />
    </>
  ),
  router: (
    <>
      <rect x="2" y="12" width="20" height="9" rx="2" />
      <path d="M6 16.5h.01M10 16.5h.01" />
      <path d="M12 8V3" />
      <path d="M8 6a5.5 5.5 0 0 1 8 0" />
    </>
  ),
  unknown: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.7" />
      <path d="M12 17h.01" />
    </>
  ),
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 16, className }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_SHAPES[name]}
    </svg>
  );
}
