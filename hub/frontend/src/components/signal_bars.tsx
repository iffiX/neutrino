import { t, useLanguage } from "../i18n";

import "./signal_bars.css";

/**
 * Wi-Fi signal strength, as four rising bars.
 *
 * A percentage is the honest number and is shown beside the bars, but the bars
 * are what makes a list of twenty networks sortable by eye.
 */

const BAR_COUNT = 4;

interface SignalBarsProps {
  percent: number;
  isLabelled?: boolean;
}

export function SignalBars({ percent, isLabelled = false }: SignalBarsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const filled = Math.max(1, Math.ceil((clamp(percent) / 100) * BAR_COUNT));
  return (
    <span
      className="signal_bars"
      title={t("ui.signal_bars.title", { percent: clamp(percent) })}
    >
      <span className={`signal_bars_stack signal_bars_stack--${tone(percent)}`}>
        {Array.from({ length: BAR_COUNT }, (_, index) => (
          <span
            key={index}
            className={`signal_bar ${index < filled ? "signal_bar--on" : ""}`}
            style={{ height: `${(index + 1) * 25}%` }}
          />
        ))}
      </span>
      {isLabelled && (
        <span className="signal_bars_text">{clamp(percent)}%</span>
      )}
    </span>
  );
}

function clamp(percent: number): number {
  return Math.min(100, Math.max(0, Math.round(percent)));
}

function tone(percent: number): string {
  if (percent >= 60) {
    return "ok";
  }
  return percent >= 30 ? "warn" : "weak";
}
