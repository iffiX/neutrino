import Foundation

/// One terminal tab: a shell session on a managed machine, opened here or listed by the hub.
struct TerminalTab: Equatable, Identifiable {
    /// The shell's session id; also the tab's id.
    let sessionId: String

    /// The hub the machine is managed by.
    let bindingId: String

    /// The machine.
    let deviceId: String

    /// The machine's name.
    let name: String

    /// The account the shell runs as, empty for the machine's first enabled one.
    var account = ""

    /// What the shell last set as its title.
    var title = ""

    /// Who opened the session, as the hub names it; empty until the hub lists it.
    var owner = ""

    /// The opener's name, as the hub lists it; empty until the hub lists it.
    var ownerName = ""

    /// Whether this phone opened the session.
    var isOwned = true

    /// Whether the session outlives every window.
    var isPersistent = false

    /// Whether every client with terminal rights on the machine lists the session.
    var isShared = false

    /// How many windows show the session, as the last state frame says.
    var attachedCount = 0

    /// Whether the hub has listed the session since the tab was made.
    var isListed = false

    /// Where the tab's stream stands.
    var phase = TerminalPhase.detached

    /// Why the shell ended, the stream dropped or a command was refused.
    var note: ClientError?

    /// The tab's id, as a list keys it.
    var id: String { sessionId }

    /// Whether closing the tab ends the session for everyone, which takes two presses.
    var isKept: Bool { isPersistent || isShared }

    /// Whether the two switches act: the tab is open and this phone opened its session.
    var canPersist: Bool { phase == .open && isOwned }

    /// Who opened the session, for the reason line of a tab this phone does not own: the name, else the stamp.
    var ownerLabel: String { ownerName.isEmpty ? owner : ownerName }
}
