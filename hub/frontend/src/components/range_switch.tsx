import "./range_switch.css";

/**
 * A row of pill buttons choosing one value out of a fixed few: the window a
 * chart draws, the share of traffic it shows, or the system a help text is
 * for. One is always on.
 */

export interface RangeOption<T extends string> {
  value: T;
  label: string;
  /** One word drawn as a badge inside the pill, where one is due. */
  badge?: string;
}

interface RangeSwitchProps<T extends string> {
  options: RangeOption<T>[];
  value: T;
  onChange: (value: T) => void;
}

export function RangeSwitch<T extends string>({
  options,
  value,
  onChange,
}: RangeSwitchProps<T>) {
  return (
    <div className="range_switch">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`range_switch_option ${
            value === option.value ? "range_switch_option--on" : ""
          }`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.badge !== undefined && (
            <span className="badge badge--accent range_switch_badge">
              {option.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
