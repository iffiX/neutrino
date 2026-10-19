import Foundation

/// Where one terminal tab's stream stands.
enum TerminalPhase {
    /// A new shell is being opened, or a listed one attached.
    case connecting
    /// The shell's stream is open.
    case open
    /// No stream is attached while the session may still run: listed and not yet shown, or a lost socket.
    case detached
    /// The session is gone from the hub's list, the shell ended, or the hub refused it.
    case ended
}
