import { useState } from "react";

import { Icon } from "./icon";
import { RangeSwitch } from "./range_switch";
import type { RangeOption } from "./range_switch";
import { t, useLanguage } from "../i18n";

import "./authority_install.css";

/**
 * Installing the hub's certificate authority on the device in front of you.
 *
 * One tab per system, the one this page is open on chosen first and marked,
 * and only the chosen system's steps drawn. With `href` a download button
 * sits above the tabs; without it the page holding this draws its own.
 */

/** The kinds of device the steps are written for, in the order listed. */
const AUTHORITY_DEVICES = [
  "windows",
  "macos",
  "linux_chrome",
  "linux_firefox",
  "ios",
  "android",
] as const;

type AuthorityDevice = (typeof AUTHORITY_DEVICES)[number];

/** How many steps each device's list has, each `ui.authority.<device>_<n>`. */
const AUTHORITY_STEP_COUNTS: Record<AuthorityDevice, number> = {
  windows: 4,
  macos: 5,
  linux_chrome: 4,
  linux_firefox: 4,
  ios: 5,
  android: 4,
};

interface AuthorityInstallProps {
  /** Where the file downloads from: the panel's route, or a blob URL. */
  href?: string;
  /** What the downloaded file is called. */
  fileName: string;
  /** Whether the download is the action this section exists for. */
  isPrimary?: boolean;
}

export function AuthorityInstall({
  href,
  fileName,
  isPrimary = false,
}: AuthorityInstallProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const current = currentDevice();
  const [device, setDevice] = useState<AuthorityDevice>(current);

  return (
    <div className="authority_install">
      {href !== undefined && (
        <a
          className={`button ${isPrimary ? "button--primary" : ""} authority_install_download`}
          href={href}
          download={fileName}
        >
          <Icon name="download" size={14} />
          {t("ui.authority.install")}
        </a>
      )}
      <RangeSwitch
        options={deviceOptions(current)}
        value={device}
        onChange={setDevice}
      />
      <ol className="authority_install_steps">
        {stepKeys(device).map((key) => (
          <li key={key}>{t(key, { file: fileName })}</li>
        ))}
      </ol>
    </div>
  );
}

function deviceOptions(
  current: AuthorityDevice,
): RangeOption<AuthorityDevice>[] {
  return AUTHORITY_DEVICES.map((device) => ({
    value: device,
    label: t(`ui.authority.device_${device}`),
    badge: device === current ? t("ui.authority.this_device") : undefined,
  }));
}

function stepKeys(device: AuthorityDevice): string[] {
  return Array.from(
    { length: AUTHORITY_STEP_COUNTS[device] },
    (_, at) => `ui.authority.${device}_${at + 1}`,
  );
}

/** Which device this page is open on, read from the browser's own report. */
function currentDevice(): AuthorityDevice {
  const agent = navigator.userAgent;
  // iPadOS asks for the desktop site and reports itself as a Mac with touch.
  if (
    /iPhone|iPad|iPod/.test(agent) ||
    (/Macintosh/.test(agent) && navigator.maxTouchPoints > 1)
  ) {
    return "ios";
  }
  if (/Android/.test(agent)) {
    return "android";
  }
  if (/Windows/.test(agent)) {
    return "windows";
  }
  if (/Macintosh|Mac OS X/.test(agent)) {
    return "macos";
  }
  return /Firefox\//.test(agent) ? "linux_firefox" : "linux_chrome";
}
