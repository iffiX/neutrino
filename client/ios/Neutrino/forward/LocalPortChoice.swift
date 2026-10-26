import Foundation

/// One entry's local port, as the table keeps it.
struct LocalPortChoice: Codable, Equatable {
    /// Whether the person set the number, in place of the hub's; otherwise it is the app's pick for a forward of
    /// no app.
    var isFixed = false

    /// The number.
    var port = 0

    /// `tcp` or `udp`; a kept entry with none reads as `tcp`.
    var `protocol` = "tcp"

    private enum CodingKeys: String, CodingKey {
        case isFixed = "is_fixed"
        case port
        case `protocol`
    }
}

extension LocalPortChoice {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        isFixed = try container.decodeIfPresent(Bool.self, forKey: .isFixed) ?? false
        port = try container.decodeIfPresent(Int.self, forKey: .port) ?? 0
        `protocol` = try container.decodeIfPresent(String.self, forKey: .protocol) ?? "tcp"
    }
}
