import Foundation

/// What a waiting hub row waits for, each worded as `ui.state.<raw value>`.
enum HubWaitReason: String {
    /// Every address of the round failed.
    case hubSilent = "hub_silent"
    /// The phone has no network at all; the next round waits for its connectivity to change.
    case noNetwork = "no_network"
    /// An address answered with another certificate.
    case untrusted
    /// The hub paused new devices; the join runs again after the seconds it named.
    case admissionPaused = "admission_paused"
    /// The hub does not know this binding; nothing runs, and Leave is the one action.
    case unknownDevice = "unknown_device"
    /// The hub speaks another protocol number; nothing runs until a refresh.
    case tooOld = "too_old"
    /// The hub refused the binding's ticket; nothing runs, and Leave is the one action.
    case joinRefused = "join_refused"
    /// Another socket for the same binding took over; nothing runs until a person reconnects.
    case replaced
    /// The hub switched this client off; the socket stays open.
    case disabled
}
