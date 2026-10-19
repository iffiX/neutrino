import Foundation

/// One service a hub publishes to this phone, as its `state` lists it.
struct ChannelServiceEntry: Equatable, Identifiable {
    /// What a `service` and a `connect` stream name.
    let id: String

    /// `web`, `port`, `ai`, `file` or `rdp`.
    let type: String

    /// The name a person reads.
    let title: String

    /// The type's own fields.
    let payload: [String: JSONValue]

    /// The module's health or the last probe's word; nil where nothing probed it.
    let isHealthy: Bool?

    /// `module`, `declared` or `device`.
    let source: String

    /// The English provenance line.
    let description: String

    /// The provenance as a code.
    let descriptionCode: String

    /// The values that sentence names.
    let descriptionParams: [String: JSONValue]

    /// The machine that provides it, empty when the hub knows none.
    let deviceName: String

    /// That machine's id, empty when no managed machine provides it.
    let deviceId: String

    /// Whether the entry is unhealthy: only an explicit `false` is.
    var isUnhealthy: Bool { isHealthy == false }

    /// Read one entry tolerantly.
    ///
    /// - Parameter value: The entry as the state carried it.
    /// - Returns: The entry, or nil for one without an id or a type.
    static func of(_ value: JSONValue) -> ChannelServiceEntry? {
        guard let object = value.objectValue else { return nil }
        let id = object.text("id")
        let type = object.text("type")
        guard !id.isEmpty, !type.isEmpty else { return nil }
        return ChannelServiceEntry(
            id: id,
            type: type,
            title: object.text("title"),
            payload: object.object("payload"),
            isHealthy: object["is_healthy"]?.boolValue,
            source: object.text("source"),
            description: object.text("description"),
            descriptionCode: object.text("description_code"),
            descriptionParams: object.object("description_params"),
            deviceName: object.text("device_name"),
            deviceId: object.text("device_id"))
    }
}
