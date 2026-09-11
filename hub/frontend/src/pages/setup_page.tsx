import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "../components/icon";
import { PasswordField } from "../components/password_field";
import { ToggleSwitch } from "../components/toggle_switch";
import {
  LANGUAGES,
  LANGUAGE_NAMES,
  setLanguage,
  t,
  useLanguage,
} from "../i18n";
import {
  panelPasswordHint,
  PANEL_PASSWORD_RULES,
  vaultPassphraseHint,
  VAULT_PASSPHRASE_RULES,
  isPasswordAccepted,
} from "../password_strength";
import type {
  SetupAnswers,
  SetupContext,
  SetupInterface,
  SetupState,
} from "../setup_api";
import { readSetupLink, readSetupState, sendSetupAnswers } from "../setup_api";

import "./setup_page.css";

/**
 * The first run, in a browser.
 *
 * The same questions the terminal asks, in the same order and with the same
 * defaults — `nhub setup` serves this while it waits, and what it gets back
 * is the answers document `--stdin` takes. Nothing is written until the last
 * screen is confirmed, so every screen can be stepped back through.
 *
 * The room is dark while it is being asked and lights up once the box is a
 * gateway, which is the same room the panel's login lives in.
 */

/** The questions, in order. The counter and the heading both read from this. */
const SCREEN_TITLES = [
  "ui.setup.screen_language",
  "ui.setup.screen_secrets",
  "ui.setup.screen_shape",
  "ui.setup.screen_ports",
  "ui.setup.screen_proxy",
  "ui.setup.screen_ready",
] as const;

/** Which screen each answer is on, so no screen is a number at the call site. */
const SCREEN_LANGUAGE = 0;
const SCREEN_SECRETS = 1;
const SCREEN_SHAPE = 2;
const SCREEN_PORTS = 3;
const SCREEN_PROXY = 4;
const SCREEN_REVIEW = SCREEN_TITLES.length - 1;

/** The product's own name, which is the same in every language. */
const SETUP_BRAND_NAME = "Neutrino Hub";

/** How often the running screen asks how far the steps have got. */
const POLL_INTERVAL_MS = 700;
/** How long the finished screen is left up before it hands over. */
const HANDOVER_SECONDS = 5;
/** How many unanswered polls mean this page is no longer on the same wire. */
const LOST_POLL_COUNT = 5;
/** Where the run writes itself down, named on the screen that warns about
 * losing the connection so somebody has read it before they need it. */
const SETUP_LOG_PATH = "/var/log/neutrino/setup.log";

/** One link on the proxy screen, as it is being filled in. */
interface DraftLink {
  /** What was typed. */
  value: string;
  /** What the hub calls the node, empty until it has read it. */
  name: string;
  /** Why the hub could not read it, empty when it could. */
  detail: string;
  /** Whether it is being edited rather than shown as what it is. */
  isEditing: boolean;
}

function emptyLink(): DraftLink {
  return { value: "", name: "", detail: "", isEditing: true };
}

interface SetupPageProps {
  /** The one-time token this page was opened with. */
  token: string;
  /** The machine's ports, modes and modules, already read. */
  context: SetupContext;
}

export function SetupPage({ token, context }: SetupPageProps) {
  // Redrawn when the language screen changes it.
  const language = useLanguage();
  const [index, setIndex] = useState(-1);
  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
  const [vaultPassphrase, setVaultPassphrase] = useState("");
  const [vaultRepeated, setVaultRepeated] = useState("");
  const [mode, setMode] = useState(context.modes[0]?.key ?? "server");
  const [wan, setWan] = useState("");
  const [lan, setLan] = useState("");
  const [address, setAddress] = useState("");
  const [prefixLen, setPrefixLen] = useState(context.defaults.prefix_len);
  const [upstream, setUpstream] = useState("");
  const [vlanId, setVlanId] = useState(context.defaults.lan_vlan_id);
  const [listenPort, setListenPort] = useState(context.defaults.listen_port);
  const [isProxyWanted, setIsProxyWanted] = useState(false);
  const [links, setLinks] = useState<DraftLink[]>([emptyLink()]);
  const [isLocalProxied, setIsLocalProxied] = useState(false);
  const [socksProxyPort, setSocksProxyPort] = useState(
    context.defaults.socks_proxy_port,
  );
  const [isSocksDirect, setIsSocksDirect] = useState(false);
  const [socksDirectPort, setSocksDirectPort] = useState(
    context.defaults.socks_direct_port,
  );
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<SetupState | null>(null);
  // Consecutive polls that got no answer. Setting a box up from a browser on
  // that same box means the address under this page can change while it is
  // open, so losing the wizard is expected rather than an error.
  const [missedPolls, setMissedPolls] = useState(0);

  const isServer = mode === "server";
  const isRouter = mode === "router";
  const isOneArm = mode === "one_arm_router";
  const isSideGateway = mode === "side_gateway";
  const chosenMode = context.modes.find((entry) => entry.key === mode);
  // Read from the mode rather than listed here: which modes address a machine
  // is the backend's answer, and two copies of it drift.
  const ownsAddressing = chosenMode?.is_addressing_owned ?? true;

  // Only the ports the chosen mode can be built on: 802.1Q tags do not ride
  // on a radio, so a trunk lists wires alone.
  const candidates = useMemo(
    () =>
      chosenMode?.is_wire_needed
        ? context.interfaces.filter((port) => port.is_wired)
        : context.interfaces,
    [chosenMode, context.interfaces],
  );

  // The ports and the address are worked out from the mode, and again from
  // the port, because a default left over from a port nobody picked is how
  // somebody agrees to a network they never chose.
  useEffect(() => {
    const uplink = uplinkDefault(candidates);
    const served = servedDefault(candidates, uplink);
    setWan(isRouter ? uplink : "");
    setLan(isRouter ? served : isSideGateway ? uplink : served);
  }, [mode, candidates, isRouter, isSideGateway]);

  useEffect(() => {
    const port = context.interfaces.find((entry) => entry.name === lan);
    const [nextAddress, nextPrefix] = addressDefault(
      mode,
      port,
      context.defaults.address,
      context.defaults.prefix_len,
    );
    setAddress(nextAddress);
    setPrefixLen(nextPrefix);
    setUpstream(port?.upstream_gateway ?? "");
  }, [lan, mode, context.interfaces, context.defaults]);

  const replaceLink = (position: number, next: DraftLink) =>
    setLinks((current) =>
      current.map((link, at) => (at === position ? next : link)),
    );

  // The hub reads the link, not this page: a second parser for one format is
  // a second thing to keep in step. A link it reads becomes a chip named
  // after the node; one it cannot says why, and holds up the screen.
  const readLink = async (position: number) => {
    const link = links[position];
    if (link === undefined || link.value.trim() === "") {
      return;
    }
    const reading = await readSetupLink(token, link.value.trim());
    replaceLink(position, {
      ...link,
      name: reading.name,
      detail: reading.detail,
      isEditing: reading.detail !== "",
    });
  };

  const named = links
    .filter((link) => link.name !== "")
    .map((link) => link.name);
  const isProxyReady =
    !isProxyWanted ||
    links.every((link) => link.value.trim() === "" || link.name !== "");

  const answers = useCallback((): SetupAnswers => {
    const network: SetupAnswers["network"] = { mode };
    if (isRouter) {
      network.wan = [wan];
      network.lan = [lan];
    } else if (isOneArm) {
      network.trunk = lan;
      network.lan_vlan_id = vlanId;
    } else if (isSideGateway) {
      network.lan = [lan];
      network.upstream_gateway = upstream;
    }
    if (!isServer) {
      network.address = address;
      network.prefix_len = prefixLen;
    }
    const document: SetupAnswers = {
      language,
      password,
      vault_passphrase: vaultPassphrase,
      network,
    };
    const wanted = links.map((link) => link.value.trim()).filter(Boolean);
    if (isProxyWanted && wanted.length > 0) {
      document.proxy = {
        links: wanted,
        is_local: isLocalProxied,
        socks_proxy_port: socksProxyPort,
        is_socks_direct_enabled: isSocksDirect,
        socks_direct_port: socksDirectPort,
      };
    }
    document.listen_port = listenPort;
    return document;
  }, [
    mode,
    isRouter,
    isOneArm,
    isServer,
    isSideGateway,
    wan,
    lan,
    vlanId,
    address,
    prefixLen,
    upstream,
    language,
    password,
    vaultPassphrase,
    links,
    isProxyWanted,
    isLocalProxied,
    socksProxyPort,
    isSocksDirect,
    socksDirectPort,
    listenPort,
  ]);

  const start = async () => {
    setError(null);
    try {
      setState(await sendSetupAnswers(token, answers()));
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  // While the steps run, the terminal is the one doing the work and this only
  // watches. A poll that stops answering means the wizard has given the
  // panel's port back, which is itself the last step.
  useEffect(() => {
    if (state === null || state.state === "done" || state.state === "failed") {
      return;
    }
    const handle = window.setInterval(() => {
      readSetupState(token)
        .then((answer) => {
          setState(answer);
          setMissedPolls(0);
        })
        .catch(() => setMissedPolls((count) => count + 1));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [state, token]);

  const isRejected = state?.state === "rejected";
  useEffect(() => {
    if (isRejected) {
      setState(null);
      setIndex(SCREEN_REVIEW);
      setError(state?.message ?? t("ui.setup.answers_refused"));
    }
  }, [isRejected, state]);

  if (state !== null && !isRejected) {
    return (
      <SetupRunning
        state={state}
        isLost={missedPolls > LOST_POLL_COUNT}
        fallbackUrl={`http://${address}:${listenPort}`}
      />
    );
  }

  const back = () => {
    setError(null);
    setIndex((current) => current - 1);
  };
  const next = () => {
    setError(null);
    setIndex((current) => current + 1);
  };

  if (index < 0) {
    return (
      <SetupFrame>
        <div className="setup_welcome">
          <h1 className="setup_welcome_title">{SETUP_BRAND_NAME}</h1>
          <p className="setup_welcome_line">{t("ui.setup.welcome_line")}</p>
          <p className="setup_welcome_note">{t("ui.setup.welcome_note")}</p>
          <button
            type="button"
            className="button button--primary setup_begin"
            onClick={next}
          >
            {t("ui.setup.start")}
            <Icon name="chevron_right" size={14} />
          </button>
        </div>
      </SetupFrame>
    );
  }

  const isPasswordReady =
    isPasswordAccepted(password, repeated, PANEL_PASSWORD_RULES) &&
    isPasswordAccepted(vaultPassphrase, vaultRepeated, VAULT_PASSPHRASE_RULES);
  const isPortsReady =
    isServer ||
    (lan !== "" &&
      address !== "" &&
      (!isRouter || (wan !== "" && wan !== lan)) &&
      (!isSideGateway || upstream !== ""));

  const actions = (
    <>
      {error !== null && (
        <div className="notice notice--error setup_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      <div className="setup_actions">
        <button type="button" className="button" onClick={back}>
          {t("ui.setup.back")}
        </button>
        {index === SCREEN_REVIEW ? (
          <button
            type="button"
            className="button button--primary"
            onClick={() => void start()}
          >
            {t("ui.setup.start")}
          </button>
        ) : (
          <button
            type="button"
            className="button button--primary"
            onClick={next}
            disabled={
              (index === SCREEN_SECRETS && !isPasswordReady) ||
              (index === SCREEN_PORTS && !isPortsReady) ||
              (index === SCREEN_PROXY && !isProxyReady)
            }
          >
            {t("ui.setup.next")}
          </button>
        )}
      </div>
    </>
  );

  return (
    <SetupFrame
      step={index + 1}
      total={SCREEN_TITLES.length}
      title={t(SCREEN_TITLES[index] ?? "")}
      actions={actions}
    >
      {index === SCREEN_LANGUAGE && (
        <div className="setup_body">
          <p className="setup_lead">{t("ui.setup.language_lead")}</p>
          <label className="field setup_field--narrow">
            <span className="field_label">{t("ui.setup.language_label")}</span>
            <select
              className="select"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
            >
              {LANGUAGES.map((offered) => (
                <option key={offered} value={offered}>
                  {LANGUAGE_NAMES[offered]}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {index === SCREEN_SECRETS && (
        <div className="setup_body">
          <p className="setup_lead">{t("ui.setup.secrets_lead")}</p>
          <PasswordField
            label={t("ui.setup.panel_password")}
            hint={panelPasswordHint}
            value={password}
            repeated={repeated}
            rules={PANEL_PASSWORD_RULES}
            autoFocus
            onChange={setPassword}
            onRepeatedChange={setRepeated}
          />
          <PasswordField
            label={t("ui.setup.vault_passphrase")}
            hint={vaultPassphraseHint}
            value={vaultPassphrase}
            repeated={vaultRepeated}
            rules={VAULT_PASSPHRASE_RULES}
            onChange={setVaultPassphrase}
            onRepeatedChange={setVaultRepeated}
          />
        </div>
      )}

      {index === SCREEN_SHAPE && (
        <div className="setup_body">
          <div className="setup_modes">
            {context.modes.map((entry) => (
              <button
                type="button"
                key={entry.key}
                className={`setup_mode ${entry.key === mode ? "setup_mode--chosen" : ""}`}
                onClick={() => setMode(entry.key)}
              >
                <span className="setup_mode_name">
                  {t(`ui.setup.mode_${entry.key}`)}
                </span>
                <span className="setup_mode_summary">
                  {t(`ui.setup.mode_summary_${entry.key}`)}
                </span>
              </button>
            ))}
          </div>
          {chosenMode?.has_caution && (
            <p className="setup_warn">
              {t(`ui.setup.mode_caution_${chosenMode.key}`)}
            </p>
          )}
        </div>
      )}

      {index === SCREEN_PORTS && isServer && (
        <div className="setup_body">
          <p className="setup_lead">{t("ui.setup.ports_server_lead")}</p>
          <PortList ports={context.interfaces} />
          <PortField
            label={t("ui.setup.panel_port")}
            value={listenPort}
            onChange={setListenPort}
          />
        </div>
      )}

      {index === SCREEN_PORTS && !isServer && (
        <div className="setup_body">
          {isRouter && (
            <p className="setup_lead">{t("ui.setup.router_note")}</p>
          )}
          {isRouter && (
            <PortChoice
              label={t("ui.setup.port_wan")}
              ports={candidates}
              chosen={wan}
              onChoose={setWan}
            />
          )}
          <PortChoice
            label={
              isRouter
                ? t("ui.setup.port_lan")
                : isOneArm
                  ? t("ui.setup.port_one_arm")
                  : isSideGateway
                    ? t("ui.setup.port_side_gateway")
                    : t("ui.setup.port_server")
            }
            ports={candidates}
            chosen={lan}
            refused={isRouter ? wan : ""}
            onChoose={setLan}
          />
          {isOneArm && (
            <label className="field">
              <span className="field_label">{t("ui.setup.vlan_tag")}</span>
              <input
                className="input"
                value={vlanId}
                inputMode="numeric"
                onChange={(event) =>
                  setVlanId(Number(event.target.value.replace(/\D/g, "")) || 0)
                }
              />
            </label>
          )}
          <div className="setup_row">
            <label className="field">
              <span className="field_label">{t("ui.setup.address")}</span>
              <input
                className="input"
                value={address}
                placeholder="192.168.8.1"
                onChange={(event) => setAddress(event.target.value.trim())}
              />
            </label>
            <label className="field setup_field--narrow">
              <span className="field_label">{t("ui.setup.prefix_len")}</span>
              <input
                className="input"
                value={prefixLen}
                inputMode="numeric"
                onChange={(event) =>
                  setPrefixLen(
                    Number(event.target.value.replace(/\D/g, "")) || 0,
                  )
                }
              />
            </label>
          </div>
          {isSideGateway && (
            <label className="field">
              <span className="field_label">
                {t("ui.setup.upstream_gateway")}
              </span>
              <input
                className="input"
                value={upstream}
                placeholder="192.168.1.1"
                onChange={(event) => setUpstream(event.target.value.trim())}
              />
            </label>
          )}
          <PortField
            label={t("ui.setup.panel_port")}
            value={listenPort}
            onChange={setListenPort}
          />
        </div>
      )}

      {index === SCREEN_PROXY && (
        <div className="setup_body">
          <p className="setup_lead">
            {isServer
              ? t("ui.setup.proxy_lead_server")
              : t("ui.setup.proxy_lead_router")}
          </p>
          <ToggleSwitch
            isOn={isProxyWanted}
            label={t("ui.setup.proxy_enable")}
            onChange={setIsProxyWanted}
          />
          {isProxyWanted && (
            <>
              <div className="field">
                <span className="field_label">{t("ui.setup.links")}</span>
                {links.map((link, position) => (
                  <div className="setup_link" key={position}>
                    {link.isEditing ? (
                      <input
                        className={`input ${link.detail !== "" ? "input--invalid" : ""}`}
                        value={link.value}
                        autoFocus={position > 0}
                        placeholder={t("ui.setup.link_placeholder")}
                        onChange={(event) =>
                          replaceLink(position, {
                            ...link,
                            value: event.target.value,
                            detail: "",
                          })
                        }
                        onBlur={() => void readLink(position)}
                      />
                    ) : (
                      <button
                        type="button"
                        className="button setup_chip"
                        title={link.value}
                        onClick={() =>
                          replaceLink(position, { ...link, isEditing: true })
                        }
                      >
                        <Icon name="nodes" size={14} />
                        <span className="setup_chip_name">{link.name}</span>
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button--ghost setup_link_drop"
                      aria-label={t("ui.setup.link_remove", {
                        number: position + 1,
                      })}
                      disabled={links.length === 1}
                      onClick={() =>
                        setLinks(links.filter((_, at) => at !== position))
                      }
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </div>
                ))}
                {links.some((link) => link.detail !== "") && (
                  <span className="field_error">
                    {links.find((link) => link.detail !== "")?.detail}
                  </span>
                )}
                <button
                  type="button"
                  className="button button--small setup_link_add"
                  onClick={() => setLinks([...links, emptyLink()])}
                >
                  <Icon name="plus" size={14} />
                  {t("ui.setup.link_add")}
                </button>
              </div>
              {isServer ? (
                <PortField
                  label={t("ui.setup.socks_proxy_port")}
                  value={socksProxyPort}
                  onChange={setSocksProxyPort}
                />
              ) : (
                <>
                  <ToggleSwitch
                    isOn={isSocksDirect}
                    label={t("ui.setup.socks_direct_enable")}
                    onChange={setIsSocksDirect}
                  />
                  {isSocksDirect && (
                    <PortField
                      label={t("ui.setup.socks_direct_port")}
                      value={socksDirectPort}
                      onChange={setSocksDirectPort}
                    />
                  )}
                </>
              )}
              <ToggleSwitch
                isOn={isLocalProxied}
                label={t("ui.setup.proxy_local")}
                onChange={setIsLocalProxied}
              />
            </>
          )}
        </div>
      )}

      {index === SCREEN_REVIEW && (
        <div className="setup_body">
          <p className="setup_lead">
            {ownsAddressing
              ? t("ui.setup.review_lead_owned")
              : t("ui.setup.review_lead_kept")}
          </p>
          {/* The same sentence the terminal says, and for the same reason:
              not whether this page is being read over one of these ports,
              which is not something to work out, but that nothing is left
              half done if it is. */}
          {ownsAddressing && (
            <div className="notice notice--warn setup_notice">
              <Icon name="alert" size={15} />
              <div className="notice_body">
                {t("ui.setup.interruption")}{" "}
                {t("ui.setup.panel_will_be_at", {
                  url: `http://${address}:${listenPort}`,
                  path: SETUP_LOG_PATH,
                })}
              </div>
            </div>
          )}
          <dl className="setup_review">
            <Row
              name={t("ui.setup.review_shape")}
              value={mode.replace(/_/g, " ")}
            />
            <Row
              name={t("ui.setup.review_language")}
              value={LANGUAGE_NAMES[language]}
            />
            {isRouter && <Row name={t("ui.setup.port_wan")} value={wan} />}
            {isServer ? (
              <Row
                name={t("ui.setup.review_answers_on")}
                value={context.interfaces.map((port) => port.name).join(", ")}
              />
            ) : (
              <Row
                name={
                  isOneArm
                    ? t("ui.setup.review_trunk")
                    : t("ui.setup.review_served_on")
                }
                value={lan}
              />
            )}
            {isOneArm && (
              <Row name={t("ui.setup.review_vlan")} value={String(vlanId)} />
            )}
            {!isServer && (
              <Row
                name={t("ui.setup.review_this_box")}
                value={`${address}/${prefixLen}`}
              />
            )}
            <Row
              name={t("ui.setup.review_panel_port")}
              value={String(listenPort)}
            />
            {isSideGateway && (
              <Row name={t("ui.setup.review_upstream")} value={upstream} />
            )}
            <Row
              name={t("ui.setup.review_proxy")}
              value={
                isProxyWanted && named.length > 0
                  ? named.join(", ")
                  : t("state.not_used")
              }
            />
          </dl>
        </div>
      )}
    </SetupFrame>
  );
}

/**
 * The room every screen is drawn in, dark until the box is a gateway.
 *
 * The card is one size for every screen, and three regions inside it: what
 * you are looking at, what you are answering, and what you press. Only the
 * middle one scrolls, and only when that screen has more to offer than fits,
 * so the heading and the buttons are always in the same place and nothing
 * moves as a screen is filled in.
 */
/**
 * A box waiting to be set up, opened without the token that reaches it.
 *
 * Drawn in the wizard's own frame rather than the panel's login card: there is
 * no panel on this machine yet, and a password field for one would be asking
 * for something that does not exist.
 */
export function SetupTokenMissing() {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <SetupFrame title={t("ui.setup.waiting_title")}>
      <div className="setup_body">
        <p className="setup_lead">{t("ui.setup.waiting_lead")}</p>
        <p className="field_hint">{t("ui.setup.waiting_hint")}</p>
      </div>
    </SetupFrame>
  );
}

function SetupFrame({
  step,
  total,
  title,
  isLit = false,
  actions,
  children,
}: {
  step?: number;
  total?: number;
  title?: string;
  isLit?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`setup_page ${isLit ? "setup_page--lit" : ""}`}>
      <div className="setup_backdrop">
        <div className="setup_orb setup_orb--cyan" />
        <div className="setup_orb setup_orb--violet" />
      </div>
      <div className="setup_stage">
        <div className="setup_card">
          <div className="setup_head">
            <div className="setup_rule">
              <span className="setup_wordmark">NEUTRINO</span>
              <span className="setup_rule_line" />
              <span className="setup_counter">
                {step === undefined
                  ? t("ui.setup.counter_idle")
                  : t("ui.setup.counter", { step, total: total ?? 0 })}
              </span>
            </div>
            {title !== undefined && <h2 className="setup_title">{title}</h2>}
          </div>
          <div className="setup_scroll">{children}</div>
          {actions !== undefined && <div className="setup_foot">{actions}</div>}
        </div>
        <div className="setup_art" />
      </div>
    </div>
  );
}

/** The steps running, and the panel to go to when they are done. */
function SetupRunning({
  state,
  isLost,
  fallbackUrl,
}: {
  state: SetupState;
  isLost: boolean;
  fallbackUrl: string;
}) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const isDone = state.state === "done";
  const isFailed = state.state === "failed";
  const panelUrl = state.panel_url || fallbackUrl;
  const [remainingS, setRemainingS] = useState(HANDOVER_SECONDS);
  // Lit one painted frame after done, never with it: a transition only runs
  // between two rendered states, and a screen that mounts already lit has
  // only one.
  const [isLit, setIsLit] = useState(false);

  useEffect(() => {
    if (!isDone) {
      return;
    }
    const outer = requestAnimationFrame(() => {
      requestAnimationFrame(() => setIsLit(true));
    });
    return () => cancelAnimationFrame(outer);
  }, [isDone]);

  // A run that finished is worth a moment to read before the page is taken
  // away from you: the steps it took are the only place several of them are
  // reported. A run that failed is never taken away — its output is what
  // somebody is about to go and act on. The countdown reaching zero is not
  // enough on its own: the panel this page goes to is still starting, so it
  // is asked first, and the page leaves only for a panel that answers.
  useEffect(() => {
    if (!isDone && !isLost) {
      return;
    }
    const handle = window.setInterval(() => {
      setRemainingS((left) => {
        if (left > 1) {
          return left - 1;
        }
        // The wizard held the panel's own port, so the panel is this page's
        // origin: a session probe answering means it is up.
        fetch("/api/auth/session")
          .then(() => window.location.assign(panelUrl))
          .catch(() => {
            // Still starting; the next tick asks again.
          });
        return 0;
      });
    }, 1000);
    return () => window.clearInterval(handle);
  }, [isDone, isLost, panelUrl]);

  return (
    <SetupFrame
      isLit={isLit}
      title={isDone ? t("ui.setup.done_title") : t("ui.setup.running_title")}
      actions={
        isDone ? (
          <div className="setup_handover">
            <p className="setup_lead">
              {t("ui.setup.handover", { seconds: remainingS })}
            </p>
            <a className="button button--primary" href={panelUrl}>
              {t("ui.setup.open_panel")}
              <Icon name="chevron_right" size={14} />
            </a>
          </div>
        ) : undefined
      }
    >
      <ol className="setup_steps">
        {state.steps.map((step) => (
          <li
            className={`setup_step setup_step--${step.status}`}
            key={`${step.id}${step.params.name ?? ""}`}
          >
            <span className="setup_step_mark" />
            <span className="setup_step_name">
              {t(`ui.setup.step_${step.id}`, step.params)}
            </span>
            <span className="setup_step_note">{step.note}</span>
          </li>
        ))}
      </ol>
      {isFailed && <p className="setup_lead">{t("ui.setup.failed_lead")}</p>}
      {isLost && !isDone && (
        <div className="notice notice--warn setup_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.setup.lost", { url: panelUrl })}
          </div>
        </div>
      )}
      {state.state === "failed" && (
        <div className="notice notice--error setup_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {state.message || t("ui.setup.step_failed")}
          </div>
        </div>
      )}
    </SetupFrame>
  );
}

function PortChoice({
  label,
  ports,
  chosen,
  refused = "",
  onChoose,
}: {
  label: string;
  ports: SetupInterface[];
  chosen: string;
  refused?: string;
  onChoose: (name: string) => void;
}) {
  return (
    <div className="field">
      <span className="field_label">{label}</span>
      <div className="setup_ports">
        {ports.map((port) => (
          <button
            type="button"
            key={port.name}
            disabled={port.name === refused}
            className={`setup_port ${port.name === chosen ? "setup_port--chosen" : ""}`}
            onClick={() => onChoose(port.name)}
          >
            <span className="setup_port_name">{port.name}</span>
            <span className="setup_port_kind">
              {port.is_wired ? t("state.wired") : t("state.wifi")}
            </span>
            <span className="setup_port_address">
              {port.ipv4_address || t("state.no_address")}
            </span>
            {port.has_route && (
              <span className="setup_port_route">
                {t("ui.setup.way_out_today")}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Every port, said rather than asked about. */
function PortList({ ports }: { ports: SetupInterface[] }) {
  return (
    <div className="field">
      <span className="field_label">{t("ui.setup.machine_ports")}</span>
      <div className="setup_ports">
        {ports.map((port) => (
          <div className="setup_port setup_port--read_only" key={port.name}>
            <span className="setup_port_name">{port.name}</span>
            <span className="setup_port_kind">
              {port.is_wired ? t("state.wired") : t("state.wifi")}
            </span>
            <span className="setup_port_address">
              {port.ipv4_address || t("state.no_address")}
            </span>
            {port.has_route && (
              <span className="setup_port_route">
                {t("ui.setup.way_out_today")}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function PortField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (port: number) => void;
}) {
  return (
    <label className="field setup_field--narrow">
      <span className="field_label">{label}</span>
      <input
        className="input"
        value={value}
        inputMode="numeric"
        onChange={(event) =>
          onChange(Number(event.target.value.replace(/\D/g, "")) || 0)
        }
      />
    </label>
  );
}

function Row({ name, value }: { name: string; value: string }) {
  return (
    <>
      <dt>{name}</dt>
      <dd>{value}</dd>
    </>
  );
}

/**
 * Which port to offer as the way out: the one carrying traffic today.
 *
 * Choosing any other is how an install ends with no way out.
 */
function uplinkDefault(ports: SetupInterface[]): string {
  return (ports.find((port) => port.has_route) ?? ports[0])?.name ?? "";
}

/**
 * Which port to offer as the served network.
 *
 * A port with no default route is not anybody's way out, which on a gateway
 * that is already running is the port that is already the LAN.
 */
function servedDefault(ports: SetupInterface[], taken: string): string {
  const free = ports.find((port) => !port.has_route && port.name !== taken);
  return (
    (free ?? ports.find((port) => port.name !== taken) ?? ports[0])?.name ?? ""
  );
}

/**
 * The address and prefix to offer, by what the port is doing.
 *
 * A one-arm router serves a VLAN that does not exist yet, so the port's own
 * address belongs to its way out and is never the answer. A box joining
 * somebody else's network keeps what the port already has. A router replaces
 * the network's gateway, so a port whose address came with a default route is
 * holding a lease that is going away.
 */
function addressDefault(
  mode: string,
  port: SetupInterface | undefined,
  freshAddress: string,
  freshPrefix: number,
): [string, number] {
  const carried = port?.ipv4_address ?? "";
  const [carriedAddress, carriedPrefix] = carried.split("/");
  const kept: [string, number] = [
    carriedAddress ?? "",
    Number(carriedPrefix) || freshPrefix,
  ];
  if (mode === "one_arm_router") {
    return [freshAddress, freshPrefix];
  }
  if (mode === "side_gateway" || mode === "server") {
    return carried ? kept : ["", freshPrefix];
  }
  if (carried && !port?.has_route) {
    return kept;
  }
  return [freshAddress, freshPrefix];
}
