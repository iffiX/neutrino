import { useCallback, useEffect, useRef, useState } from "react";

import { DeviceGauge } from "./device_gauge";
import { DialogLayer } from "./dialog_layer";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import { providerLabel } from "../ai_provider_labels";
import { monthLabel } from "../ai_usage";
import { ApiError, apiGet, apiPost, describeError } from "../api_client";
import { copyText } from "../copy_text";
import { formatDuration, formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { usePolledResource } from "../use_polled_resource";
import { useConfirm } from "../use_confirm";
import { useTableCards } from "../use_table_cards";
import type { StatusTone } from "./status_dot";
import type {
  CliproxyApiAccountView,
  CliproxyApiAccountsResponse,
  CliproxyApiLoginStartView,
  CliproxyApiLoginStateView,
  CliproxyApiQuotaWindowView,
} from "../api_types";

import "./ai_accounts_panel.css";
import "./confirm_modal.css";

/**
 * The subscriptions the gateway serves from, beside the keyed providers.
 *
 * An account is a login the box holds rather than a token somebody pasted, so
 * nothing here stages: signing in writes the credential the moment the
 * provider hands it over, a refresh, a pause and a resume write at once, and
 * deleting one is a revocation, which never waits behind an apply bar. The
 * panel therefore carries no frame to light. The accounts are a table of
 * one line each while the panel's box holds every column and each line's
 * buttons, and a card each in a narrower box: the service and the label
 * with the limit windows under it, the counts, the status and the updated
 * time at the right, and the buttons at its foot.
 *
 * A sign-in is one interaction that has to finish, so it happens in a modal:
 * the provider decides how — a redirect the person brings back, or a code they
 * type at the provider — and the gateway says which of the two this build
 * offers for each service.
 */

const ACCOUNTS_PATH = "/hub/ai/gateway/account";
const LOGIN_PATH = "/hub/ai/gateway/account_login";

/** A sign-in is watched while somebody waits on it; the list is not. */
const LOGIN_POLL_INTERVAL_MS = 2000;
/** How often the device-flow deadline redraws. */
const COUNTDOWN_TICK_MS = 1000;
const COPIED_CLEAR_MS = 1600;

/** The one `status` a working account reports. */
const ACCOUNT_STATUS_ACTIVE = "active";

/** A window's ring turns amber from this used percent, and red at full. */
const QUOTA_WARN_PERCENT = 80;
const QUOTA_ERROR_PERCENT = 100;

/** The word under the ring of each window the hub names. */
const WINDOW_WORD_KEYS: Record<string, string> = {
  "5h": "ui.ai.quota_5h",
  "7d": "ui.ai.quota_7d",
  month: "ui.ai.quota_month",
};

/** The sentence keying each error code the accounts endpoints return. */
const ERROR_KEYS: Record<string, string> = {
  unknown_account: "code.unknown_account",
  login_expired: "code.login_expired",
  gateway_unreachable: "code.gateway_unreachable",
  management_key_missing: "code.management_key_missing",
};

export function AiAccountsPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource =
    usePolledResource<CliproxyApiAccountsResponse>(ACCOUNTS_PATH);
  const confirm = useConfirm();
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { reload, setData } = resource;
  const tableBoxRef = useRef<HTMLDivElement>(null);
  const isCards = useTableCards(tableBoxRef, ".ai_account_actions");
  const accounts = resource.data?.accounts ?? [];
  const loginKinds = resource.data?.login_kinds ?? [];
  const hasKinds = loginKinds.length > 0;

  const handleSignedIn = useCallback(() => {
    setIsSigningIn(false);
    reload();
  }, [reload]);

  const handleDelete = async (account: CliproxyApiAccountView) => {
    setIsBusy(true);
    setError(null);
    try {
      setData(
        await apiPost<CliproxyApiAccountsResponse>(
          "/hub/ai/gateway/account/remove",
          { name: account.name },
        ),
      );
    } catch (cause: unknown) {
      setError(wordError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askDelete = (account: CliproxyApiAccountView) => {
    confirm.ask({
      title: t("ui.ai.account_delete_title", {
        account: accountLabel(account),
      }),
      body: t("ui.ai.account_delete_body"),
      confirmLabel: t("ui.ai.delete"),
      onConfirm: () => void handleDelete(account),
    });
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.ai.accounts_title")}</h2>
        <button
          type="button"
          className="button credentials_section_action"
          disabled={!hasKinds || isBusy}
          title={hasKinds ? undefined : t("ui.ai.no_login_kinds")}
          onClick={() => {
            setIsSigningIn(true);
          }}
        >
          <Icon name="plus" size={14} />
          {t("ui.ai.sign_in")}
        </button>
      </div>
      <p className="field_hint">{t("ui.ai.accounts_hint")}</p>

      {resource.error !== null && (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      )}

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {resource.data === null && resource.error === null && (
        <div className="skeleton" style={{ height: 76 }} />
      )}

      {resource.data !== null &&
        (accounts.length === 0 ? (
          <div className="placeholder">
            <span>{t("ui.ai.accounts_empty")}</span>
            <span className="faint">{t("ui.ai.accounts_empty_hint")}</span>
          </div>
        ) : (
          <div
            ref={tableBoxRef}
            className={`ai_accounts_box ${isCards ? "ai_accounts_box--cards" : ""}`}
          >
            <table className="ai_accounts">
              <colgroup>
                <col className="ai_accounts_col--service" />
                <col className="ai_accounts_col--identity" />
                <col className="ai_accounts_col--windows" />
                <col className="ai_accounts_col--counts" />
                <col className="ai_accounts_col--status" />
                <col className="ai_accounts_col--updated" />
                <col className="ai_accounts_col--actions" />
              </colgroup>
              <thead className="ai_accounts_head">
                <tr>
                  <th />
                  <th />
                  <th />
                  <th />
                  <th />
                  <th />
                  <th />
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <AccountRow
                    key={account.name}
                    value={account}
                    isBusy={isBusy}
                    onChanged={setData}
                    onDelete={() => {
                      askDelete(account);
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {isSigningIn && (
        <AccountLoginModal
          kinds={loginKinds}
          onSignedIn={handleSignedIn}
          onDismiss={() => {
            setIsSigningIn(false);
          }}
        />
      )}
      {confirm.modal}
    </section>
  );
}

interface AccountRowProps {
  value: CliproxyApiAccountView;
  isBusy: boolean;
  /** A refresh, a pause or a resume landed, with the list it returned. */
  onChanged: (view: CliproxyApiAccountsResponse) => void;
  onDelete: () => void;
}

/** One account: who it is, what it is doing, its windows, and the ways to
 * read its quota, pause it and revoke it. */
function AccountRow({ value, isBusy, onChanged, onDelete }: AccountRowProps) {
  const [pending, setPending] = useState<"refresh" | "pause" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const health = describeAccount(value);
  const hasMessage = value.status_message.length > 0;
  const newestSeenAt = newestSeen(value.windows);

  const write = async (path: string, action: "refresh" | "pause") => {
    setPending(action);
    setError(null);
    try {
      onChanged(
        await apiPost<CliproxyApiAccountsResponse>(path, { name: value.name }),
      );
    } catch (cause: unknown) {
      setError(wordError(cause));
    } finally {
      setPending(null);
    }
  };

  return (
    <tr className="ai_account_row">
      <td className="ai_account_cell--service">
        <span className="key_card_type">{providerLabel(value.provider)}</span>
      </td>
      <td className="ai_account_cell--identity">
        <span className="ai_account_identity">
          <span className="ai_account_name">{accountLabel(value)}</span>
          {value.plan.length > 0 && (
            <span className="ai_account_plan faint">
              {t("ui.ai.plan", { plan: value.plan })}
            </span>
          )}
          {value.subscription_ends_at.length > 0 && (
            <span className="ai_account_plan faint">
              {t("ui.ai.plan_until", {
                date: formatDay(value.subscription_ends_at),
              })}
            </span>
          )}
        </span>
        {error !== null && (
          <span className="field_error ai_account_error">{error}</span>
        )}
      </td>
      <td className="ai_account_cell--windows">
        {value.windows.length > 0 && (
          <span className="ai_account_windows">
            {value.windows.map((window) => (
              <span
                key={window.name}
                className="ai_account_window"
                title={
                  window.resets_at.length > 0
                    ? t("ui.ai.quota_resets", {
                        time: formatMoment(window.resets_at),
                      })
                    : undefined
                }
              >
                <DeviceGauge
                  label={windowWord(window.name)}
                  reading={window.used_share * 100}
                  warnAt={QUOTA_WARN_PERCENT}
                  errorAt={QUOTA_ERROR_PERCENT}
                />
                {window.resets_at.length > 0 && (
                  <span className="ai_account_resets faint">
                    {t("ui.ai.quota_resets", {
                      time: formatShortMoment(window.resets_at),
                    })}
                  </span>
                )}
              </span>
            ))}
          </span>
        )}
      </td>
      <td className="ai_account_cell--counts">
        <span className="ai_account_counts">
          <span>{t("ui.ai.count_ok", { count: value.success_count })}</span>
          <span>·</span>
          <span
            className={
              value.failed_count > 0 ? "ai_account_counts--failed" : undefined
            }
          >
            {t("ui.ai.count_failed", { count: value.failed_count })}
          </span>
        </span>
      </td>
      <td
        className="ai_account_cell--status"
        title={hasMessage ? value.status_message : undefined}
      >
        <StatusDot tone={health.tone} label={health.word} />
      </td>
      <td className="ai_account_cell--updated">
        {newestSeenAt !== null && (
          <span className="ai_account_updated faint">
            {t("ui.ai.quota_updated", { ago: formatTimeAgo(newestSeenAt) })}
          </span>
        )}
      </td>
      <td className="ai_account_cell--actions">
        <span className="ai_account_actions">
          {value.has_quota_read && (
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={isBusy || pending !== null}
              onClick={() =>
                void write("/hub/ai/gateway/account/quota/scan", "refresh")
              }
            >
              {pending === "refresh" ? (
                <Spinner size={12} />
              ) : (
                <Icon name="refresh" size={13} />
              )}
              {t("ui.ai.refresh")}
            </button>
          )}
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isBusy || pending !== null}
            onClick={() =>
              void write(
                value.is_disabled
                  ? "/hub/ai/gateway/account/enable"
                  : "/hub/ai/gateway/account/disable",
                "pause",
              )
            }
          >
            <span className="ai_account_pause_words">
              <span aria-hidden={value.is_disabled}>{t("ui.ai.pause")}</span>
              <span aria-hidden={!value.is_disabled}>{t("ui.ai.resume")}</span>
            </span>
          </button>
          <button
            type="button"
            className="button button--ghost button--small button--danger"
            disabled={isBusy || pending !== null}
            onClick={onDelete}
          >
            <Icon name="trash" size={13} />
            {t("ui.ai.delete")}
          </button>
        </span>
      </td>
    </tr>
  );
}

interface AccountLoginModalProps {
  /** The sign-ins this gateway build offers, in the order it listed them. */
  kinds: string[];
  /** An account landed: close, and let the list pick it up. */
  onSignedIn: () => void;
  /** Closed before it finished; the flow behind it is already cancelled. */
  onDismiss: () => void;
}

/**
 * One sign-in, from picking a service to the credential landing.
 *
 * The redirect flow keeps polling while the paste field waits, because some
 * providers hand the code back to the gateway themselves and the person then
 * has nothing to paste.
 */
function AccountLoginModal({
  kinds,
  onSignedIn,
  onDismiss,
}: AccountLoginModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [login, setLogin] = useState<CliproxyApiLoginStartView | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isFinishing, setIsFinishing] = useState(false);
  const [pasted, setPasted] = useState("");
  // How a flow ended without signing in: the words, and the gateway's own
  // reason under them when it sent one. The dialog keeps its screen.
  const [failure, setFailure] = useState<LoginFailure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  const dismiss = useCallback(() => {
    if (login !== null) {
      void discardLogin(login.state);
    }
    onDismiss();
  }, [login, onDismiss]);

  // A finished flow is not asked about again, and neither is one that failed
  // or expired.
  const watchedLogin = failure === null ? login : null;
  useEffect(() => {
    if (watchedLogin === null) {
      return;
    }
    let isCancelled = false;
    const tick = async () => {
      if (document.hidden) {
        return;
      }
      try {
        const next = await apiGet<CliproxyApiLoginStateView>(LOGIN_PATH, {
          state: watchedLogin.state,
        });
        if (isCancelled) {
          return;
        }
        if (next.status === "complete") {
          onSignedIn();
        } else if (next.status === "failed") {
          setFailure(failedLogin(next));
        }
      } catch (cause: unknown) {
        if (!isCancelled && isExpired(cause)) {
          setFailure(EXPIRED_LOGIN);
        }
        // Any other failure is passing; the next tick asks again.
      }
    };
    const handle = window.setInterval(
      () => void tick(),
      LOGIN_POLL_INTERVAL_MS,
    );
    return () => {
      isCancelled = true;
      window.clearInterval(handle);
    };
  }, [watchedLogin, onSignedIn]);

  useEffect(() => {
    if (login === null || login.expires_in <= 0) {
      setSecondsLeft(null);
      return;
    }
    const deadline = Date.now() + login.expires_in * 1000;
    const update = () => {
      setSecondsLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    };
    update();
    const handle = window.setInterval(update, COUNTDOWN_TICK_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [login]);

  const isPasteReady = pasted.trim().length > 0;
  const isRedirect = login !== null && login.flow === "redirect";

  const handleStart = async (kind: string) => {
    setIsStarting(true);
    setError(null);
    setFailure(null);
    setPasted("");
    try {
      setLogin(
        await apiPost<CliproxyApiLoginStartView>(
          "/hub/ai/gateway/account_login/start",
          { kind },
        ),
      );
    } catch (cause: unknown) {
      setError(wordError(cause));
    } finally {
      setIsStarting(false);
    }
  };

  const handleFinish = async () => {
    if (login === null) {
      return;
    }
    setIsFinishing(true);
    setError(null);
    try {
      const next = await apiPost<CliproxyApiLoginStateView>(
        "/hub/ai/gateway/account_login/code/set",
        { state: login.state, code: pasted.trim() },
      );
      if (next.status === "complete") {
        onSignedIn();
      } else if (next.status === "failed") {
        setFailure(failedLogin(next));
      }
    } catch (cause: unknown) {
      if (isExpired(cause)) {
        setFailure(EXPIRED_LOGIN);
      } else {
        setError(wordError(cause));
      }
    } finally {
      setIsFinishing(false);
    }
  };

  const handleRetry = () => {
    const kind = login?.kind ?? null;
    setFailure(null);
    setError(null);
    setLogin(null);
    setPasted("");
    if (kind !== null) {
      void handleStart(kind);
    }
  };

  return (
    <DialogLayer label={t("ui.ai.sign_in_title")} onDismiss={dismiss}>
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="key" size={16} />
          <h2>
            {login === null
              ? t("ui.ai.sign_in_title")
              : t("ui.ai.sign_in_with", {
                  provider: providerLabel(login.kind),
                })}
          </h2>
        </div>

        <div className="confirm_body ai_login_body">
          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}

          {failure !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">
                {t(failure.key)}
                {failure.message !== "" && (
                  <div className="mono faint">{failure.message}</div>
                )}
              </div>
            </div>
          )}

          {login === null ? (
            <div className="ai_login_kinds">
              {kinds.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="button ai_login_kind"
                  disabled={isStarting}
                  onClick={() => void handleStart(kind)}
                >
                  {t("ui.ai.continue_with", {
                    provider: providerLabel(kind),
                  })}
                </button>
              ))}
            </div>
          ) : (
            <>
              <p className="ai_login_hint">
                {isRedirect ? t("ui.ai.redirect_hint") : t("ui.ai.device_hint")}
              </p>

              <div className="ai_login_url_row">
                <a
                  className="ai_login_url mono"
                  href={login.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {login.url}
                </a>
                <CopyButton value={login.url} />
              </div>

              {!isRedirect && (
                <div className="ai_login_code_row">
                  <span className="ai_login_code mono">{login.user_code}</span>
                  <CopyButton value={login.user_code} />
                </div>
              )}

              {isRedirect && (
                <label className="field">
                  <span className="field_label">{t("ui.ai.paste_label")}</span>
                  <input
                    className="input"
                    value={pasted}
                    autoFocus
                    spellCheck={false}
                    placeholder={t("ui.ai.paste_placeholder")}
                    onChange={(event) => {
                      setPasted(event.target.value);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && isPasteReady) {
                        void handleFinish();
                      }
                    }}
                  />
                </label>
              )}

              {failure === null && (
                <div className="ai_login_waiting">
                  <StatusDot
                    tone="warn"
                    label={t("ui.ai.sign_in_waiting")}
                    isPulsing
                  />
                  {secondsLeft !== null && (
                    <span className="ai_login_expiry mono">
                      {secondsLeft > 0
                        ? t("ui.ai.expires_in", {
                            left: formatDuration(secondsLeft),
                          })
                        : t("ui.ai.expired")}
                    </span>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="confirm_foot">
          <button type="button" className="button" onClick={dismiss}>
            {t("ui.ai.cancel")}
          </button>
          {failure !== null && (
            <button
              type="button"
              className="button button--primary"
              disabled={isStarting}
              onClick={handleRetry}
            >
              <Icon name="refresh" size={14} />
              {t("ui.ai.try_again")}
            </button>
          )}
          {failure === null && isRedirect && (
            <button
              type="button"
              className="button button--primary"
              disabled={!isPasteReady || isFinishing}
              onClick={() => void handleFinish()}
            >
              <Icon name="check" size={14} />
              {isFinishing ? t("ui.ai.finishing") : t("ui.ai.finish")}
            </button>
          )}
        </div>
      </div>
    </DialogLayer>
  );
}

interface CopyButtonProps {
  value: string;
}

/** Copy one value, confirming in place the way every other copy here does. */
function CopyButton({ value }: CopyButtonProps) {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copyText(value);
      setIsCopied(true);
      window.setTimeout(() => {
        setIsCopied(false);
      }, COPIED_CLEAR_MS);
    } catch {
      // The value is on screen; copying by hand still works.
    }
  };

  return (
    <button
      type="button"
      className="button button--small"
      onClick={() => void handleCopy()}
    >
      <Icon name={isCopied ? "check" : "file"} size={13} />
      {isCopied ? t("ui.ai.copied") : t("ui.ai.copy")}
    </button>
  );
}

/** How a flow ended without signing in. */
interface LoginFailure {
  /** The catalog key of the words. */
  key: string;
  /** The gateway's own reason, empty when it sent none. */
  message: string;
}

const EXPIRED_LOGIN: LoginFailure = { key: "code.login_expired", message: "" };

function failedLogin(view: CliproxyApiLoginStateView): LoginFailure {
  return { key: "ui.ai.sign_in_failed", message: view.message.trim() };
}

/** Whether a call failed because the sign-in session ended first. */
function isExpired(cause: unknown): boolean {
  return cause instanceof ApiError && cause.code === "login_expired";
}

/** Drop a sign-in nobody finished; it expires anyway if this never lands. */
async function discardLogin(state: string): Promise<void> {
  try {
    await apiPost("/hub/ai/gateway/account_login/stop", { state });
  } catch {
    // Nothing on screen waits on the cancel being accepted.
  }
}

/** What names an account here: its label, else its email, else its file. */
function accountLabel(account: CliproxyApiAccountView): string {
  if (account.label.length > 0) {
    return account.label;
  }
  if (account.email.length > 0) {
    return account.email;
  }
  return account.name;
}

/**
 * The dot and the word one account wears.
 *
 * A paused account shows as paused before any failure, and a cooling one
 * with the time it serves again.
 */
function describeAccount(account: CliproxyApiAccountView): {
  tone: StatusTone;
  word: string;
} {
  if (account.is_disabled) {
    return { tone: "idle", word: t("state.paused") };
  }
  if (account.is_unavailable && account.next_retry_after.length > 0) {
    return {
      tone: "warn",
      word: t("ui.ai.limited_until", {
        time: formatMoment(account.next_retry_after),
      }),
    };
  }
  if (account.is_unavailable || account.status !== ACCOUNT_STATUS_ACTIVE) {
    return { tone: "error", word: t("state.unavailable") };
  }
  return { tone: "ok", word: t("state.serving") };
}

/** The word under a window's ring: its own word, else its name. */
function windowWord(name: string): string {
  const key = WINDOW_WORD_KEYS[name];
  return key === undefined ? name : t(key);
}

/** The time the newest of the windows was seen, null with none. */
function newestSeen(windows: CliproxyApiQuotaWindowView[]): string | null {
  let newest: string | null = null;
  let newestAt = Number.NEGATIVE_INFINITY;
  for (const window of windows) {
    const at = Date.parse(window.seen_at);
    if (!Number.isNaN(at) && at > newestAt) {
      newest = window.seen_at;
      newestAt = at;
    }
  }
  return newest;
}

/** A day as `Nov 26`, or the stamp itself while it will not parse. */
function formatDay(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return isoTimestamp;
  }
  const date = new Date(parsed);
  return t("ui.usage.bucket_day", {
    month: monthLabel(date.getMonth()),
    day: date.getDate(),
  });
}

/** A local clock time as `14:05` today, else its day alone as `Nov 29`. */
function formatShortMoment(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return isoTimestamp;
  }
  const date = new Date(parsed);
  return date.toDateString() === new Date().toDateString()
    ? formatHourMinute(date)
    : formatDay(isoTimestamp);
}

function formatHourMinute(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** A local clock time as `14:05`, after its day when that is not today. */
function formatMoment(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return isoTimestamp;
  }
  const date = new Date(parsed);
  const clock = formatHourMinute(date);
  return date.toDateString() === new Date().toDateString()
    ? clock
    : `${formatDay(isoTimestamp)} ${clock}`;
}

/** A failed sign-in's own reason, or the plain sentence where it sent none. */
/** The sentence for a failed call, from the code the API named it with. */
function wordError(cause: unknown): string {
  if (!(cause instanceof ApiError)) {
    return describeError(cause);
  }
  if (cause.code === "unsupported_kind") {
    const kind = readParam(cause.detail, "kind");
    if (kind.length > 0) {
      return t("code.unsupported_kind", { provider: providerLabel(kind) });
    }
  }
  if (cause.code === "quota_read_unsupported") {
    return t("code.quota_read_unsupported", {
      provider: providerLabel(readParam(cause.detail, "provider")),
    });
  }
  const key = ERROR_KEYS[cause.code];
  return key === undefined ? describeError(cause) : t(key);
}

/** One value out of an error's `params`, empty where the API sent none. */
function readParam(detail: unknown, key: string): string {
  const params = asRecord(asRecord(detail)?.params);
  const value = params?.[key];
  return typeof value === "string" ? value : "";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  return value as Record<string, unknown>;
}
