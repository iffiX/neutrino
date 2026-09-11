import { useCallback, useEffect, useState } from "react";

import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import {
  ApiError,
  apiDelete,
  apiPost,
  apiPut,
  describeError,
} from "../api_client";
import { copyText } from "../copy_text";
import { formatDuration } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { usePolledResource } from "../use_polled_resource";
import { useConfirm } from "../use_confirm";
import type { StatusTone } from "./status_dot";
import type {
  CliproxyApiAccountView,
  CliproxyApiAccountsResponse,
  CliproxyApiLoginStartView,
  CliproxyApiLoginStateView,
} from "../api_types";

import "./ai_accounts_panel.css";
import "./confirm_modal.css";

/**
 * The subscriptions the gateway serves from, beside the keyed providers.
 *
 * An account is a login the box holds rather than a token somebody pasted, so
 * nothing here stages: signing in writes the credential the moment the
 * provider hands it over, and deleting one is a revocation, which never waits
 * behind an apply bar. The panel therefore carries no frame to light.
 *
 * A sign-in is one interaction that has to finish, so it happens in a modal:
 * the provider decides how — a redirect the person brings back, or a code they
 * type at the provider — and the gateway says which of the two this build
 * offers for each service.
 */

const ACCOUNTS_PATH = "/cliproxyapi/accounts";
const LOGINS_PATH = "/cliproxyapi/account_logins";

/** A sign-in is watched while somebody waits on it; the list is not. */
const LOGIN_POLL_INTERVAL_MS = 2000;
/** How often the device-flow deadline redraws. */
const COUNTDOWN_TICK_MS = 1000;
const COPIED_CLEAR_MS = 1600;

/** The one `status` a working account reports. */
const ACCOUNT_STATUS_ACTIVE = "active";

/**
 * What each service is called on this page.
 *
 * A login kind is the protocol the gateway speaks, an account's provider the
 * file it was written to, and the two spell one service differently; both
 * spellings are worded here. Anything else shows the name the gateway used.
 */
const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Claude",
  claude: "Claude",
  codex: "ChatGPT",
  antigravity: "Google",
  kimi: "Kimi",
  xai: "xAI",
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
        await apiDelete<CliproxyApiAccountsResponse>(
          `${ACCOUNTS_PATH}/${encodeURIComponent(account.name)}`,
        ),
      );
    } catch (cause: unknown) {
      setError(wordError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askDelete = (account: CliproxyApiAccountView) =>
    confirm.ask({
      title: t("ui.ai.account_delete_title", {
        account: accountLabel(account),
      }),
      body: t("ui.ai.account_delete_body"),
      confirmLabel: t("ui.ai.delete"),
      onConfirm: () => void handleDelete(account),
    });

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.ai.accounts_title")}</h2>
        <button
          type="button"
          className="button button--primary credentials_section_action"
          disabled={!hasKinds || isBusy}
          title={hasKinds ? undefined : t("ui.ai.no_login_kinds")}
          onClick={() => setIsSigningIn(true)}
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
          <div className="ai_accounts">
            {accounts.map((account) => (
              <AccountRow
                key={account.name}
                value={account}
                isBusy={isBusy}
                onDelete={() => askDelete(account)}
              />
            ))}
          </div>
        ))}

      {isSigningIn && (
        <AccountLoginModal
          kinds={loginKinds}
          onSignedIn={handleSignedIn}
          onDismiss={() => setIsSigningIn(false)}
        />
      )}
      {confirm.modal}
    </section>
  );
}

interface AccountRowProps {
  value: CliproxyApiAccountView;
  isBusy: boolean;
  onDelete: () => void;
}

/** One account: who it is, what it is doing, and the way to revoke it. */
function AccountRow({ value, isBusy, onDelete }: AccountRowProps) {
  const health = describeAccount(value);
  const hasMessage = value.status_message.length > 0;

  return (
    <div className="ai_account_row">
      <span className="key_card_type">{providerLabel(value.provider)}</span>
      <span className="ai_account_label">{accountLabel(value)}</span>
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
      <span
        className="ai_account_status"
        title={hasMessage ? value.status_message : undefined}
      >
        <StatusDot tone={health.tone} label={health.word} />
      </span>
      <button
        type="button"
        className="button button--ghost button--small button--danger"
        disabled={isBusy}
        onClick={onDelete}
      >
        <Icon name="trash" size={13} />
        {t("ui.ai.delete")}
      </button>
    </div>
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
  const [failure, setFailure] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  // A finished flow is not asked about again, and neither is one that failed.
  const statePath =
    login === null || failure !== null
      ? null
      : `${LOGINS_PATH}/${encodeURIComponent(login.state)}`;
  const watched = usePolledResource<CliproxyApiLoginStateView>(
    statePath,
    LOGIN_POLL_INTERVAL_MS,
  );
  const watchedState = watched.data;

  const dismiss = useCallback(() => {
    if (login !== null) {
      void discardLogin(login.state);
    }
    onDismiss();
  }, [login, onDismiss]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dismiss();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [dismiss]);

  useEffect(() => {
    if (watchedState === null) {
      return;
    }
    if (watchedState.status === "complete") {
      onSignedIn();
    } else if (watchedState.status === "failed") {
      setFailure(sentenceFor(watchedState.message));
    }
  }, [watchedState, onSignedIn]);

  useEffect(() => {
    if (login === null || login.expires_in <= 0) {
      setSecondsLeft(null);
      return;
    }
    const deadline = Date.now() + login.expires_in * 1000;
    const update = () =>
      setSecondsLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    update();
    const handle = window.setInterval(update, COUNTDOWN_TICK_MS);
    return () => window.clearInterval(handle);
  }, [login]);

  const isPasteReady = pasted.trim().length > 0;
  const isRedirect = login !== null && login.flow === "redirect";

  const handleStart = async (kind: string) => {
    setIsStarting(true);
    setError(null);
    setFailure(null);
    setPasted("");
    try {
      setLogin(await apiPost<CliproxyApiLoginStartView>(LOGINS_PATH, { kind }));
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
      const next = await apiPut<CliproxyApiLoginStateView>(
        `${LOGINS_PATH}/${encodeURIComponent(login.state)}/code`,
        { code: pasted.trim() },
      );
      if (next.status === "complete") {
        onSignedIn();
      } else if (next.status === "failed") {
        setFailure(sentenceFor(next.message));
      }
    } catch (cause: unknown) {
      setError(wordError(cause));
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
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={t("ui.ai.sign_in_title")}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          dismiss();
        }
      }}
    >
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

          {failure !== null ? (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{failure}</div>
            </div>
          ) : login === null ? (
            <div className="ai_login_kinds">
              <p className="field_hint">{t("ui.ai.sign_in_pick_hint")}</p>
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
                    onChange={(event) => setPasted(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && isPasteReady) {
                        void handleFinish();
                      }
                    }}
                  />
                </label>
              )}

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
    </div>
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
      window.setTimeout(() => setIsCopied(false), COPIED_CLEAR_MS);
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

/** Drop a sign-in nobody finished; it expires anyway if this never lands. */
async function discardLogin(state: string): Promise<void> {
  try {
    await apiDelete(`${LOGINS_PATH}/${encodeURIComponent(state)}`);
  } catch {
    // Nothing on screen waits on the cancel being accepted.
  }
}

/** The name one service goes by, or the gateway's own where none is worded. */
function providerLabel(name: string): string {
  return PROVIDER_LABELS[name] ?? name;
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
 * A disabled account answers first: it is off by hand, not by failure.
 */
function describeAccount(account: CliproxyApiAccountView): {
  tone: StatusTone;
  word: string;
} {
  if (account.is_disabled) {
    return { tone: "idle", word: t("state.disabled") };
  }
  if (account.is_unavailable || account.status !== ACCOUNT_STATUS_ACTIVE) {
    return { tone: "error", word: t("state.unavailable") };
  }
  return { tone: "ok", word: t("state.serving") };
}

/** A failed sign-in's own reason, or the plain sentence where it sent none. */
function sentenceFor(message: string): string {
  return message.length > 0 ? message : t("ui.ai.sign_in_failed");
}

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
