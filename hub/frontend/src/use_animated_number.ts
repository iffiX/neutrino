import { useEffect, useRef, useState } from "react";

/**
 * Tween a number towards its new value instead of snapping to it.
 *
 * Stat tiles update every two seconds off the stats socket; easing the change
 * over a few hundred milliseconds is what makes the dashboard read as live
 * rather than as a page that keeps redrawing.
 */

const DEFAULT_DURATION_MS = 480;

/**
 * Animate towards a target number.
 *
 * Args:
 *   target: The value to move to. A non-finite target is shown immediately.
 *   durationMs: How long the tween takes.
 *
 * Returns:
 *   The current interpolated value for this frame.
 */
export function useAnimatedNumber(
  target: number,
  durationMs: number = DEFAULT_DURATION_MS,
): number {
  const [displayed, setDisplayed] = useState(target);
  // Mirrors the displayed value so a tween that is interrupted by a new
  // target resumes from where it actually is, without the effect depending on
  // the state it sets.
  const displayedRef = useRef(target);

  useEffect(() => {
    const from = displayedRef.current;
    if (!Number.isFinite(target) || from === target) {
      displayedRef.current = target;
      setDisplayed(target);
      return;
    }

    let frame = 0;
    const startedAt = performance.now();

    const step = (now: number) => {
      const progress = Math.min((now - startedAt) / durationMs, 1);
      const value = from + (target - from) * easeOut(progress);
      displayedRef.current = value;
      setDisplayed(value);
      if (progress < 1) {
        frame = requestAnimationFrame(step);
      }
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);

  return displayed;
}

function easeOut(progress: number): number {
  return 1 - (1 - progress) ** 3;
}
