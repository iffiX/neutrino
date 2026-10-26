import Foundation

/// One app a hub publishes to this phone: one program on one machine, whose `web`, `port` and `ssh` entries name
/// it by `id`.
struct ChannelApp: Equatable, Identifiable {
    /// The app's id, which its entries carry as `app_id`.
    let id: String

    /// The name a person reads.
    let title: String

    /// `module`, `declared` or `manual`, worded as `ui.app_source.<source>`.
    let source: String

    /// The machine that provides it, empty when no managed machine does.
    let deviceId: String

    /// That machine's name, empty when the hub knows none.
    let deviceName: String

    /// The name its entries open under on the loopback, `<app>.<machine>.localhost`.
    let localName: String

    /// Read one app tolerantly.
    ///
    /// - Parameter value: The app as the state carried it.
    /// - Returns: The app, or nil for one without an id.
    static func of(_ value: JSONValue) -> ChannelApp? {
        guard let object = value.objectValue else { return nil }
        let id = object.text("id")
        guard !id.isEmpty else { return nil }
        return ChannelApp(
            id: id,
            title: object.text("title"),
            source: object.text("source"),
            deviceId: object.text("device_id"),
            deviceName: object.text("device_name"),
            localName: object.text("local_name"))
    }
}
