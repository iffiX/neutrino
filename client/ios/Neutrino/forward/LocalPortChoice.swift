import Foundation

/// One entry's local port: automatic, with the number picked for it, or fixed by the person.
struct LocalPortChoice: Codable, Equatable {
    /// Whether the person fixed the number.
    var isFixed = false

    /// The number held: the automatic pick, or the fixed number; 0 before the first pick.
    var port = 0

    private enum CodingKeys: String, CodingKey {
        case isFixed = "is_fixed"
        case port
    }
}

extension LocalPortChoice {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        isFixed = try container.decodeIfPresent(Bool.self, forKey: .isFixed) ?? false
        port = try container.decodeIfPresent(Int.self, forKey: .port) ?? 0
    }
}
