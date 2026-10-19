import Foundation

/// The tones a status marker takes.
enum DotTone {
    /// Green: connected, healthy.
    case ok
    /// Amber and still: not connected with nothing for a person to do, disabled, unhealthy.
    case wait
    /// Grey: never reached.
    case off
    /// Red: a code a person has to act on.
    case bad
    /// Amber and pulsing: connecting, or a job running on the row.
    case pulse
}
