import Foundation

/// One shell session as the hub lists it in a `terminals` entry: every session this phone owns, and every
/// shared session on a machine it has terminal rights on.
struct ChannelTerminalSession: Equatable {
    /// What a `shell` stream and the `persist` and `stop_session` commands name.
    let sessionId: String

    /// What the shell last set as its title.
    let title: String

    /// Who opened it: `hub` for the panel, `client:<id>` for a client.
    let owner: String

    /// The opener's name: the hub's name, the owning client's name, else empty.
    let ownerName: String

    /// Whether this phone opened it.
    let isOwned: Bool

    /// Whether it outlives every window.
    let isPersistent: Bool

    /// Whether every client with terminal rights on the machine lists it.
    let isShared: Bool

    /// How many windows show it now.
    let attachedCount: Int

    /// Read one session tolerantly.
    ///
    /// - Parameter value: The session as the state carried it.
    /// - Returns: The session, or nil for one without an id.
    static func of(_ value: JSONValue) -> ChannelTerminalSession? {
        guard let object = value.objectValue else { return nil }
        let sessionId = object.text("session_id")
        guard !sessionId.isEmpty else { return nil }
        return ChannelTerminalSession(
            sessionId: sessionId,
            title: object.text("title"),
            owner: object.text("owner"),
            ownerName: object.text("owner_name"),
            isOwned: object.flag("is_owned"),
            isPersistent: object.flag("is_persistent"),
            isShared: object.flag("is_shared"),
            attachedCount: object.number("attached_count") ?? 0)
    }
}
