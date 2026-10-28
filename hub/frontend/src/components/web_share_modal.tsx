import { useState } from "react";

import { CopyButton } from "./copy_button";
import { DialogFrame } from "./dialog_frame";
import { EnrollmentLink } from "./enrollment_link";
import { Icon } from "./icon";
import { Picker } from "./picker";
import type { PickerOption } from "./picker";
import { RangeSwitch } from "./range_switch";
import type { RangeOption } from "./range_switch";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type {
  ClientListView,
  WebShareCreateRequest,
  WebShareCreatedView,
  WebShareEntryView,
} from "../api_types";

import "./web_share_modal.css";

/**
 * The **New Web share link** dialog: the share's name, the app it offers,
 * how long it lasts and the site that serves its page, then the link and
 * its QR code, given this once, and the guest account's e-mail where the
 * app signs visitors in as one.
 */

const CREATE_PATH = "/hub/client/web_share/create";

/** The four lengths a share takes, by the value the switch holds. */
type ExpiresChoice = "1" | "7" | "30" | "revoked";

const EXPIRES_KEYS: Record<ExpiresChoice, string> = {
  "1": "ui.web_shares.expires_1d",
  "7": "ui.web_shares.expires_7d",
  "30": "ui.web_shares.expires_30d",
  revoked: "ui.web_shares.until_revoked",
};
const EXPIRES_ORDER: ExpiresChoice[] = ["1", "7", "30", "revoked"];
const EXPIRES_DEFAULT: ExpiresChoice = "7";

/** The site picker's row for a copy of the page a person hosts. */
const SITE_OTHER = "other";
const SITE_OTHER_PLACEHOLDER = "https://";

interface WebShareModalProps {
  listView: ClientListView;
  /** The entry chosen at the start, as the Services page's Share names it. */
  entryId?: string;
  /** Called once a share was made, so the page reads the new row. */
  onCreated: () => void;
  onClose: () => void;
}

export function WebShareModal({
  listView,
  entryId,
  onCreated,
  onClose,
}: WebShareModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const entries = listView.web_share_entries;
  const sites = listView.web_share_sites;
  const [name, setName] = useState("");
  const [chosenEntry, setChosenEntry] = useState<string | null>(
    entries.some((entry) => entry.entry_id === entryId)
      ? (entryId ?? null)
      : null,
  );
  const [expires, setExpires] = useState<ExpiresChoice>(EXPIRES_DEFAULT);
  const [site, setSite] = useState<string>(sites[0]?.url ?? SITE_OTHER);
  const [otherSite, setOtherSite] = useState("");
  const [created, setCreated] = useState<WebShareCreatedView | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entry = entries.find((item) => item.entry_id === chosenEntry) ?? null;
  const isReady = name.trim() !== "" && entry !== null;

  const create = async () => {
    if (!isReady || entry === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    const request: WebShareCreateRequest = {
      name: name.trim(),
      entry_id: entry.entry_id,
      days: expires === "revoked" ? null : Number(expires),
      site: site === SITE_OTHER ? otherSite.trim() : site,
    };
    try {
      setCreated(await apiPost<WebShareCreatedView>(CREATE_PATH, request));
      onCreated();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const foot =
    created === null ? (
      <button
        type="button"
        className="button button--primary button--commit"
        disabled={isBusy || !isReady}
        onClick={() => void create()}
      >
        {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
        {t("ui.clients.generate_link")}
      </button>
    ) : (
      <button
        type="button"
        className="button button--primary button--commit"
        onClick={onClose}
      >
        <Icon name="check" size={14} />
        {t("ui.clients.done")}
      </button>
    );

  return (
    <DialogFrame
      title={t("ui.web_shares.new_link")}
      icon="link"
      onClose={onClose}
      foot={foot}
    >
      {created === null ? (
        <>
          <label className="field">
            <span className="field_label">{t("ui.web_shares.field_name")}</span>
            <input
              className="input"
              value={name}
              autoFocus
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void create();
                }
              }}
            />
          </label>
          <Picker
            options={entries.map(toEntryOption)}
            value={chosenEntry}
            onChange={setChosenEntry}
            label={t("ui.web_shares.field_app")}
            emptyText={t("ui.services.group_empty")}
          />
          {entry !== null && entry.guest_login === "run_account" && (
            <div className="notice notice--warn">
              <Icon name="alert" size={15} />
              <div className="notice_body">
                {t("ui.web_shares.run_account_warning", {
                  account: entry.visitor_account,
                })}
              </div>
            </div>
          )}
          <div className="field">
            <span className="field_label">
              {t("ui.web_shares.field_expires")}
            </span>
            <RangeSwitch
              options={expiresOptions()}
              value={expires}
              onChange={setExpires}
            />
          </div>
          <Picker
            options={siteOptions(listView)}
            value={site}
            onChange={setSite}
            label={t("ui.web_shares.field_site")}
          />
          {site === SITE_OTHER && (
            <label className="field">
              <input
                className="input mono"
                value={otherSite}
                placeholder={SITE_OTHER_PLACEHOLDER}
                aria-label={t("ui.web_shares.site_other")}
                onChange={(event) => setOtherSite(event.target.value)}
              />
              <span className="field_hint">
                {t("ui.web_shares.site_other_hint")}
              </span>
            </label>
          )}
        </>
      ) : (
        <>
          <strong>{created.share.name}</strong>
          <EnrollmentLink
            link={created.link}
            expiresInS={0}
            hintKey="ui.web_shares.link_once"
          />
          {created.share.guest_email !== "" && (
            <div className="web_share_guest">
              <div className="enrollment_link_row">
                <code>{created.share.guest_email}</code>
                <CopyButton text={created.share.guest_email} />
              </div>
              <p className="field_hint">{t("ui.web_shares.guest_hint")}</p>
            </div>
          )}
        </>
      )}
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </DialogFrame>
  );
}

/** One shareable entry as the App picker lists it. */
function toEntryOption(entry: WebShareEntryView): PickerOption {
  return {
    id: entry.entry_id,
    name: entry.title,
    detail: entry.device_name,
  };
}

/** The four lengths, worded. */
function expiresOptions(): RangeOption<ExpiresChoice>[] {
  return EXPIRES_ORDER.map((value) => ({
    value,
    label: t(EXPIRES_KEYS[value]),
  }));
}

/** The listed sites, then Another site. */
function siteOptions(listView: ClientListView): PickerOption[] {
  return [
    ...listView.web_share_sites.map((site) => ({
      id: site.url,
      name: site.title,
      detail: site.url,
    })),
    { id: SITE_OTHER, name: t("ui.web_shares.site_other") },
  ];
}
