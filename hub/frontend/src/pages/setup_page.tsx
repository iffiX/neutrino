import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "../components/icon";
import { Meter } from "../components/meter";
import { PasswordInput } from "../components/password_input";
import { ToggleSwitch } from "../components/toggle_switch";
import { PASSWORD_MIN_LENGTH, passwordStrength } from "../password_strength";
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
const SCREENS = [
  "A password for the panel",
  "What is this machine for?",
  "Which ports?",
  "Going out through a proxy",
  "What else to install on this box",
  "Ready",
] as const;

/** How often the running screen asks how far the steps have got. */
const POLL_INTERVAL_MS = 700;
/** How long the finished screen is left up before it hands over. */
const HANDOVER_SECONDS = 5;
/** How many unanswered polls mean this page is no longer on the same wire. */
const LOST_POLL_COUNT = 5;

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
  const [index, setIndex] = useState(-1);
  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
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
  const [services, setServices] = useState<string[]>([]);
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
    } else {
      network.lan = [lan];
    }
    network.address = address;
    network.prefix_len = prefixLen;
    if (isSideGateway) {
      network.upstream_gateway = upstream;
    }
    const document: SetupAnswers = { password, network };
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
    if (services.length > 0) {
      document.services = services;
    }
    document.listen_port = listenPort;
    return document;
  }, [
    mode,
    isRouter,
    isOneArm,
    isSideGateway,
    wan,
    lan,
    vlanId,
    address,
    prefixLen,
    upstream,
    password,
    links,
    isProxyWanted,
    isLocalProxied,
    socksProxyPort,
    isSocksDirect,
    socksDirectPort,
    services,
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
      setIndex(SCREENS.length - 1);
      setError(state?.message ?? "the answers were refused");
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
          <h1 className="setup_welcome_title">Neutrino Hub</h1>
          <p className="setup_welcome_line">
            Pour a coffee and sit back — this takes about a minute.
          </p>
          <p className="setup_welcome_note">
            Nothing is written until the last screen confirms it, and Back steps
            through the questions again.
          </p>
          <button
            type="button"
            className="button button--primary setup_begin"
            onClick={next}
          >
            Set this box up
            <Icon name="chevron_right" size={14} />
          </button>
        </div>
      </SetupFrame>
    );
  }

  const strength = passwordStrength(password);
  const isPasswordReady = strength.is_allowed && password === repeated;
  const isPortsReady =
    lan !== "" &&
    address !== "" &&
    (!isRouter || (wan !== "" && wan !== lan)) &&
    (!isSideGateway || upstream !== "");

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
          Back
        </button>
        {index === SCREENS.length - 1 ? (
          <button
            type="button"
            className="button button--primary"
            onClick={() => void start()}
          >
            Set this box up
          </button>
        ) : (
          <button
            type="button"
            className="button button--primary"
            onClick={next}
            disabled={
              (index === 0 && !isPasswordReady) ||
              (index === 2 && !isPortsReady) ||
              (index === 3 && !isProxyReady)
            }
          >
            Next
          </button>
        )}
      </div>
    </>
  );

  return (
    <SetupFrame
      step={index + 1}
      total={SCREENS.length}
      title={SCREENS[index]}
      actions={actions}
    >
      {index === 0 && (
        <div className="setup_body">
          <p className="setup_lead">
            At least {PASSWORD_MIN_LENGTH} characters, and better for mixing
            letters, numbers and symbols.
          </p>
          <label className="field">
            <span className="field_label setup_field_head">
              <span>Panel password</span>
              <Meter
                percent={strength.percent}
                tone={strength.tone}
                label={strength.label}
              />
            </span>
            <PasswordInput value={password} autoFocus onChange={setPassword} />
            {password !== "" && !strength.is_allowed && (
              <span className="field_error">
                Too short: {PASSWORD_MIN_LENGTH} characters at the very least.
              </span>
            )}
          </label>
          <label className="field">
            <span className="field_label">Again</span>
            <PasswordInput value={repeated} onChange={setRepeated} />
            {repeated !== "" && password !== repeated && (
              <span className="field_error">They do not match.</span>
            )}
          </label>
        </div>
      )}

      {index === 1 && (
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
                  {entry.key.replace(/_/g, " ")}
                </span>
                <span className="setup_mode_summary">{entry.summary}</span>
              </button>
            ))}
          </div>
          {chosenMode?.caution && (
            <p className="setup_warn">{chosenMode.caution}</p>
          )}
        </div>
      )}

      {index === 2 && (
        <div className="setup_body">
          {isRouter && <p className="setup_lead">{context.router_note}</p>}
          {isRouter && (
            <PortChoice
              label="Out to the internet"
              ports={candidates}
              chosen={wan}
              onChoose={setWan}
            />
          )}
          <PortChoice
            label={
              isRouter
                ? "In to your devices"
                : isOneArm
                  ? "The one port, out and in"
                  : isSideGateway
                    ? "Port on that network"
                    : "Port the panel answers on"
            }
            ports={candidates}
            chosen={lan}
            refused={isRouter ? wan : ""}
            onChoose={setLan}
          />
          {isOneArm && (
            <label className="field">
              <span className="field_label">VLAN tag for your devices</span>
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
              <span className="field_label">This box&apos;s address</span>
              <input
                className="input"
                value={address}
                placeholder="192.168.8.1"
                onChange={(event) => setAddress(event.target.value.trim())}
              />
            </label>
            <label className="field setup_field--narrow">
              <span className="field_label">Prefix length</span>
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
                That network&apos;s own router
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
            label="Panel answers on port"
            value={listenPort}
            onChange={setListenPort}
          />
        </div>
      )}

      {index === 3 && (
        <div className="setup_body">
          <p className="setup_lead">
            Send {isServer ? "this box's own traffic" : "your devices' traffic"}{" "}
            out through an exit node you own. Skipping is a real answer: a hub
            is a hub without a proxy, and the Proxy page turns one on later
            without any of this being redone.
          </p>
          <ToggleSwitch
            isOn={isProxyWanted}
            label="Set it up here"
            onChange={setIsProxyWanted}
          />
          {isProxyWanted && (
            <>
              <div className="field">
                <span className="field_label">Exit node links</span>
                {links.map((link, position) => (
                  <div className="setup_link" key={position}>
                    {link.isEditing ? (
                      <input
                        className={`input ${link.detail !== "" ? "input--invalid" : ""}`}
                        value={link.value}
                        autoFocus={position > 0}
                        placeholder="ss:// or vless://"
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
                      aria-label={`Remove link ${position + 1}`}
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
                  Add another
                </button>
              </div>
              {isServer ? (
                <PortField
                  label="SOCKS port applications point at"
                  value={socksProxyPort}
                  onChange={setSocksProxyPort}
                />
              ) : (
                <>
                  <ToggleSwitch
                    isOn={isSocksDirect}
                    label="Also publish a SOCKS port that bypasses the proxy"
                    onChange={setIsSocksDirect}
                  />
                  {isSocksDirect && (
                    <PortField
                      label="SOCKS port for that"
                      value={socksDirectPort}
                      onChange={setSocksDirectPort}
                    />
                  )}
                </>
              )}
              <ToggleSwitch
                isOn={isLocalProxied}
                label="Send this box's own traffic through it"
                onChange={setIsLocalProxied}
              />
            </>
          )}
        </div>
      )}

      {index === 4 && (
        <div className="setup_body">
          {context.services.length === 0 ? (
            <p className="setup_lead">
              Nothing else runs on this machine&apos;s architecture.
            </p>
          ) : (
            <>
              <p className="setup_lead">
                Installing only. What each one is for is a page of its own, once
                the panel is up.
              </p>
              {context.services.map((service) => (
                <div className="setup_service" key={service.name}>
                  <ToggleSwitch
                    // Already there is already on, and not something this
                    // screen can undo: it installs, and the panel's Services
                    // page is what removes.
                    isOn={
                      service.is_installed || services.includes(service.name)
                    }
                    isDisabled={service.is_installed}
                    label={service.name}
                    badge={
                      service.is_installed ? (
                        <span className="badge badge--ok">installed</span>
                      ) : undefined
                    }
                    description={service.install_note}
                    onChange={(isOn) =>
                      setServices((current) =>
                        isOn
                          ? [...current, service.name]
                          : current.filter((name) => name !== service.name),
                      )
                    }
                  />
                  {services.includes(service.name) &&
                    service.consents.length > 0 && (
                      <ul className="setup_consents">
                        {service.consents.map((sentence) => (
                          <li key={sentence}>{sentence}</li>
                        ))}
                      </ul>
                    )}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {index === 5 && (
        <div className="setup_body">
          <p className="setup_lead">
            This is what the box becomes. Confirming applies it: the ports
            change, the firewall loads and the services start.
          </p>
          <dl className="setup_review">
            <Row name="Shape" value={mode.replace(/_/g, " ")} />
            {isRouter && <Row name="Out to the internet" value={wan} />}
            <Row name={isOneArm ? "Trunk" : "Served on"} value={lan} />
            {isOneArm && <Row name="VLAN tag" value={String(vlanId)} />}
            <Row name="This box" value={`${address}/${prefixLen}`} />
            <Row name="Panel port" value={String(listenPort)} />
            {isSideGateway && <Row name="Its own router" value={upstream} />}
            <Row
              name="Proxy"
              value={
                isProxyWanted && named.length > 0
                  ? named.join(", ")
                  : "not used"
              }
            />
            <Row
              name="Also installing"
              value={services.length > 0 ? services.join(", ") : "nothing"}
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
                {step === undefined ? "Setup" : `Config ${step}/${total}`}
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
  const isDone = state.state === "done";
  const isFailed = state.state === "failed";
  const panelUrl = state.panel_url || fallbackUrl;
  const [remainingS, setRemainingS] = useState(HANDOVER_SECONDS);

  // A run that finished is worth a moment to read before the page is taken
  // away from you: the steps it took are the only place several of them are
  // reported. A run that failed is never taken away — its output is what
  // somebody is about to go and act on.
  useEffect(() => {
    if (!isDone && !isLost) {
      return;
    }
    const handle = window.setInterval(() => {
      setRemainingS((left) => {
        if (left > 1) {
          return left - 1;
        }
        window.location.assign(panelUrl);
        return 0;
      });
    }, 1000);
    return () => window.clearInterval(handle);
  }, [isDone, isLost, panelUrl]);

  return (
    <SetupFrame
      isLit={isDone}
      title={isDone ? "This box is a gateway" : "Making it so"}
      actions={
        isDone ? (
          <div className="setup_handover">
            <p className="setup_lead">
              The panel is starting. This page goes there in {remainingS}
              {remainingS === 1 ? " second" : " seconds"}.
            </p>
            <a className="button button--primary" href={panelUrl}>
              Open the panel
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
            key={step.description}
          >
            <span className="setup_step_mark" />
            <span className="setup_step_name">{step.description}</span>
            <span className="setup_step_note">{step.note}</span>
          </li>
        ))}
      </ol>
      {isFailed && (
        <p className="setup_lead">
          Nothing else will happen here. The terminal that started this has the
          command output that explains it.
        </p>
      )}
      {isLost && !isDone && (
        <div className="notice notice--warn setup_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            This page is no longer on the same wire as the box — its ports are
            being taken over, which is one of the steps. The work carries on
            there. It will be at {panelUrl}.
          </div>
        </div>
      )}
      {state.state === "failed" && (
        <div className="notice notice--error setup_notice">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {state.message || "a step failed; the terminal has the output"}
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
              {port.is_wired ? "wired" : "wifi"}
            </span>
            <span className="setup_port_address">
              {port.ipv4_address || "no address"}
            </span>
            {port.has_route && (
              <span className="setup_port_route">the way out today</span>
            )}
          </button>
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
