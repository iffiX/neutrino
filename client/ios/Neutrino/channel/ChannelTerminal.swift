import Foundation

/// A managed machine this phone may open a shell on, with the sessions it sees there.
struct ChannelTerminal: Equatable, Identifiable {
    /// What a `shell` stream names.
    let deviceId: String

    /// The machine's name.
    let name: String

    /// Whether its agent is connected now.
    let isOnline: Bool

    /// The Terminal module's enabled accounts there, the first being the default.
    var accounts: [String] = []

    /// The shell sessions this phone sees on it.
    let sessions: [ChannelTerminalSession]

    /// The machine's id, as a list keys it.
    var id: String { deviceId }

    /// Read one entry tolerantly.
    ///
    /// - Parameter value: The entry as the state carried it.
    /// - Returns: The machine, or nil for one without an id.
    static func of(_ value: JSONValue) -> ChannelTerminal? {
        guard let object = value.objectValue else { return nil }
        let deviceId = object.text("device_id")
        guard !deviceId.isEmpty else { return nil }
        return ChannelTerminal(
            deviceId: deviceId,
            name: object.text("name"),
            isOnline: object.flag("is_online"),
            accounts: (object["accounts"]?.arrayValue ?? []).compactMap(\.stringValue),
            sessions: (object["sessions"]?.arrayValue ?? []).compactMap { ChannelTerminalSession.of($0) })
    }
}
