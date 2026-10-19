import Foundation

/// The Keychain item's document: this installation's id and every binding.
struct BindingFile: Codable, Equatable {
    /// This installation's id, empty before the first read.
    var machineId = ""

    /// Every binding, in the order joined.
    var bindings: [HubBinding] = []

    private enum CodingKeys: String, CodingKey {
        case machineId = "machine_id"
        case bindings
    }
}

extension BindingFile {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        machineId = try container.decodeIfPresent(String.self, forKey: .machineId) ?? ""
        bindings = try container.decodeIfPresent([HubBinding].self, forKey: .bindings) ?? []
    }
}
