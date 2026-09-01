import { useEffect, useRef, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPut, describeError } from "../api_client";
import { interruptionWarning } from "../network_warnings";
import { useApiResource } from "../use_api_resource";
import type { PanelSettings } from "../api_types";

import "./panel_port_panel.css";

/**
 * The port the panel itself answers on.
 *
 * Every other service settles its port in its own tab; the panel is a service
 * too, and the only place its port had been asked for was the setup wizard. It
 * belongs on this page because it is a question about how the box is reached,
 * which is what the rest of the page is.
 *
 * Applying restarts the panel. The answer is written before the socket closes,
 * and this waits for the new port to answer and goes there — the address does
 * not change, so where to look is known exactly.
 */

const PORT_MIN = 1;
const PORT_MAX = 65535;
// How long the panel gets to come back before that is called a failure. It
// is a process restart, not a reboot; a machine that has not answered in this
// long has something else wrong with it.
const MOVE_TIMEOUT_MS = 30000;
const MOVE_POLL_MS = 500;

export function PanelPortPanel() {
  const resource = useApiResource<PanelSettings>("/settings");
  const [port, setPort] = useState<number | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [movingTo, setMovingTo] = useState<number | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setPort(resource.data.listen_port);
    }
  }, [resource.data]);

  const applied = resource.data?.listen_port ?? null;
  const isDirty = port !== null && applied !== null && port !== applied;

  const apply = async () => {
    if (port === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const saved = await apiPut<PanelSettings>("/settings", {
        listen_port: port,
      });
      resource.setData(saved);
      setMovingTo(saved.listen_port);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>Panel port</h2>
      </div>
      <p className="field_hint">
        The TCP port this panel listens on, on every exposed interface.
      </p>

      {resource.data === null ? (
        <div className="skeleton" style={{ height: 72 }} />
      ) : (
        <div className="field_grid">
          <label className="field">
            <span className="field_label">Port</span>
            <input
              className="input"
              value={port === null ? "" : String(port)}
              inputMode="numeric"
              onChange={(event) => {
                setError(null);
                setPort(Number(event.target.value) || 0);
              }}
            />
            <span className="field_hint">
              {isDirty
                ? `Moves to ${originWith(port ?? 0)}.`
                : `Reached at ${originWith(applied ?? 0)}.`}
            </span>
          </label>
        </div>
      )}

      <ApplyBar
        isDirty={isDirty && isValid(port)}
        isBusy={isBusy}
        label="Apply panel port"
        hint={
          isValid(port)
            ? "Restarts the panel service and follows it to the new port."
            : `A port is ${PORT_MIN} to ${PORT_MAX}.`
        }
        warning={interruptionWarning("The panel restarts on the new port.")}
        error={error}
        onReset={() => setPort(applied)}
        onApply={() => void apply()}
      />

      {movingTo !== null && <MovingOverlay port={movingTo} />}
    </section>
  );
}

/**
 * The wait between the old port closing and the new one answering.
 *
 * Polling the new origin rather than counting seconds: a restart takes as long
 * as it takes, and the panel answering is the only thing that means it is
 * over. A session cookie is not scoped to a port, so arriving there is
 * arriving signed in.
 */
function MovingOverlay({ port }: { port: number }) {
  const startedAt = useRef(Date.now());
  const [isLost, setIsLost] = useState(false);

  useEffect(() => {
    const destination = originWith(port);
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt.current > MOVE_TIMEOUT_MS) {
        window.clearInterval(timer);
        setIsLost(true);
        return;
      }
      // no-cors: the answer is unreadable across origins, and it does not
      // need reading — a response at all is the panel being back.
      void fetch(`${destination}/api/auth/session`, {
        mode: "no-cors",
        cache: "no-store",
      })
        .then(() => {
          window.clearInterval(timer);
          window.location.replace(destination);
        })
        .catch(() => undefined);
    }, MOVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [port]);

  return (
    <div className="panel_move">
      {isLost ? (
        <>
          <Icon name="alert" size={16} />
          <div className="panel_move_body">
            No answer at {originWith(port)}. Open it again once the panel is
            reachable from here.
          </div>
        </>
      ) : (
        <>
          <Spinner />
          <div className="panel_move_body">Moving to {originWith(port)}.</div>
        </>
      )}
    </div>
  );
}

function isValid(port: number | null): boolean {
  return port !== null && port >= PORT_MIN && port <= PORT_MAX;
}

function originWith(port: number): string {
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}
