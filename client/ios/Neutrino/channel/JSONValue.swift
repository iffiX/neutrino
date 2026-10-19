import Foundation

/// One JSON value, read tolerantly from a frame, a link or a file, and written exactly as built.
enum JSONValue: Equatable {
    /// A string.
    case string(String)
    /// A whole number.
    case int(Int)
    /// A number with a fraction.
    case double(Double)
    /// `true` or `false`.
    case bool(Bool)
    /// A list.
    case array([JSONValue])
    /// An object.
    case object([String: JSONValue])
    /// `null`.
    case null

    /// The string, or nil for any other kind.
    var stringValue: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    /// The whole number, or nil for any other kind.
    var intValue: Int? {
        switch self {
        case .int(let value): return value
        case .double(let value): return value == value.rounded() ? Int(exactly: value) : nil
        default: return nil
        }
    }

    /// The boolean, or nil for any other kind.
    var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    /// The object, or nil for any other kind.
    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    /// The list, or nil for any other kind.
    var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    /// The value as a sentence fills it in: a primitive's own text, a list or an object as JSON, null as empty.
    var text: String {
        switch self {
        case .string(let value): return value
        case .int(let value): return String(value)
        case .double(let value): return String(value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return ""
        case .array, .object: return String(decoding: encoded(), as: UTF8.self)
        }
    }

    /// The value written as compact JSON.
    ///
    /// - Returns: The UTF-8 bytes.
    func encoded() -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes, .sortedKeys]
        return (try? encoder.encode(self)) ?? Data("null".utf8)
    }

    /// Read one JSON document.
    ///
    /// - Parameter data: The UTF-8 bytes.
    /// - Returns: The value.
    /// - Throws: `DecodingError` when the bytes are not JSON.
    static func parse(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// Read one JSON object.
    ///
    /// - Parameter text: The text.
    /// - Returns: The object, or nil when the text is not a JSON object.
    static func parseObject(_ text: String) -> [String: JSONValue]? {
        (try? parse(Data(text.utf8)))?.objectValue
    }
}

extension JSONValue: Codable {
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

extension Dictionary where Key == String, Value == JSONValue {
    /// One field as text.
    ///
    /// - Parameter name: The field.
    /// - Returns: Its string, or empty when it is absent or not a string.
    func text(_ name: String) -> String {
        self[name]?.stringValue ?? ""
    }

    /// One field as a whole number.
    ///
    /// - Parameter name: The field.
    /// - Returns: Its number, or nil when it is absent or not a whole number.
    func number(_ name: String) -> Int? {
        self[name]?.intValue
    }

    /// One field as a boolean.
    ///
    /// - Parameter name: The field.
    /// - Returns: Its value, false when it is absent or not a boolean.
    func flag(_ name: String) -> Bool {
        self[name]?.boolValue ?? false
    }

    /// One field as an object.
    ///
    /// - Parameter name: The field.
    /// - Returns: Its object, empty when it is absent or not an object.
    func object(_ name: String) -> [String: JSONValue] {
        self[name]?.objectValue ?? [:]
    }

    /// The object written as compact JSON text.
    var jsonText: String {
        String(decoding: JSONValue.object(self).encoded(), as: UTF8.self)
    }
}
