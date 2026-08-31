import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Icon } from "../components/icon";
import { apiGet, describeError } from "../api_client";
import { PasswordInput } from "../components/password_input";
import { useAuth } from "../use_auth";
import type { AuthState } from "../api_types";

import "./login_page.css";

/**
 * The gate in front of everything else.
 *
 * There is one password for the whole appliance, so this is deliberately
 * plain: one field, one button, and a clear message when the gateway itself
 * cannot be reached — which looks very different from a wrong password and
 * should not be confused with one.
 *
 * Repeated failures lock the gate for longer and longer, and the locked gate
 * does not pretend otherwise: the form gives way to a countdown and the room
 * turns red. The owner clears it early with `nhub unlock` on the box.
 */

export function LoginPage() {
  const { login, error: sessionError } = useAuth();

  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Unix millis when the lockout ends, or null while login is open.
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // The clock only ticks while locked, so it must be brought to the present
  // the moment a lockout starts — a stale clock would flash a wrong first
  // number until the first tick.
  const startLockdown = (seconds: number) => {
    const current = Date.now();
    setNow(current);
    setLockedUntil(current + seconds * 1000);
  };

  // A page opened mid-lockout should show the countdown straight away.
  useEffect(() => {
    let isCancelled = false;
    apiGet<AuthState>("/auth/session")
      .then((state) => {
        if (!isCancelled && state.lockout_remaining_s > 0) {
          startLockdown(state.lockout_remaining_s);
        }
      })
      .catch(() => {
        // Unreachable API is the session probe's story to tell.
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (lockedUntil === null) {
      return;
    }
    const handle = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(handle);
  }, [lockedUntil]);

  const remainingS =
    lockedUntil === null
      ? 0
      : Math.max(0, Math.ceil((lockedUntil - now) / 1000));
  const isLocked = lockedUntil !== null && remainingS > 0;
  if (lockedUntil !== null && remainingS === 0) {
    setLockedUntil(null);
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length === 0) {
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const state = await login(password);
      if (!state.is_authenticated) {
        setPassword("");
        if (state.lockout_remaining_s > 0) {
          startLockdown(state.lockout_remaining_s);
          setError(null);
        } else {
          setError("Wrong password.");
        }
      }
    } catch (cause: unknown) {
      setError(describeError(cause));
      setPassword("");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={`login_page ${isLocked ? "login_page--lockdown" : ""}`}>
      <div className="login_backdrop">
        <div className="login_orb login_orb--cyan" />
        <div className="login_orb login_orb--violet" />
      </div>

      <div className="login_card">
        <div className="login_brand">
          <span className="login_brand_mark">
            <Icon name="proxy" size={20} />
          </span>
          <span className="login_brand_text">
            <span className="login_brand_name">Neutrino Hub</span>
            <span className="login_brand_sub">control panel</span>
          </span>
        </div>

        {isLocked ? (
          <div className="login_lockdown">
            <Icon name="lock" size={18} className="login_lockdown_icon" />
            <span className="login_lockdown_clock">
              {formatCountdown(remainingS)}
            </span>
            <span className="login_lockdown_text">
              Locked after repeated failures.
            </span>
          </div>
        ) : (
          <form
            className="login_form"
            onSubmit={(event) => void handleSubmit(event)}
          >
            <label className="field">
              <span className="field_label">Panel password</span>
              <PasswordInput
                value={password}
                autoFocus
                placeholder="••••••••"
                onChange={(next) => {
                  setError(null);
                  setPassword(next);
                }}
              />
            </label>

            {error !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{error}</div>
              </div>
            )}

            {error === null && sessionError !== null && (
              <div className="notice notice--warn">
                <Icon name="alert" size={15} />
                <div className="notice_body">
                  Could not reach the gateway API: {sessionError}
                </div>
              </div>
            )}

            <button
              type="submit"
              className="button button--primary login_submit"
              disabled={isSubmitting || password.length === 0}
            >
              <Icon name="lock" size={14} />
              {isSubmitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function formatCountdown(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}
