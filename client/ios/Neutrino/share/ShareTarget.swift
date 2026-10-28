import Foundation

/// One published share as the share page opens it.
struct ShareTarget: Equatable, Identifiable {
    /// The hub whose channel carries the share's connections.
    let bindingId: String

    /// The `file` entry each `connect` stream names.
    let entryId: String

    /// The share's title, and `<share> (<account>)` for a folder share's entry, a row of its own for each account
    /// the share is open to.
    let title: String

    /// The share's name on its server.
    let share: String

    /// The accounts the hub names for it; empty when it names none.
    let users: [String]

    /// Whether a declared app names the share, a NAS's share opened with the person's own login; a machine's share
    /// opens with the login the hub hands at every connect.
    var isDeclared = false

    /// The account a folder share's entry logs in as; empty for any other share. The hub hands that account's login
    /// at every connect.
    var account = ""

    /// `<binding>/<entry>`, the key of its row, its login and its page.
    var id: String { "\(bindingId)/\(entryId)" }

    /// The share a `file` entry names.
    ///
    /// - Parameters:
    ///   - hub: The hub that publishes it.
    ///   - entry: The entry.
    /// - Returns: The share, or nil for an entry that names no share or another protocol than SMB.
    static func of(_ hub: HubView, _ entry: ChannelServiceEntry) -> ShareTarget? {
        let share = entry.payload.text("share")
        guard entry.type == "file", entry.payload.text("protocol") == "smb", !share.isEmpty else { return nil }
        let account = entry.payload.text("account")
        return ShareTarget(
            bindingId: hub.binding.id, entryId: entry.id,
            title: account.isEmpty ? entry.title : "\(entry.title) (\(account))", share: share,
            users: entry.payload["users"]?.arrayValue?.compactMap(\.stringValue) ?? [],
            isDeclared: entry.source == "declared", account: account)
    }
}
