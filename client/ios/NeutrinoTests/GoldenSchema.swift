import Foundation
import XCTest

@testable import Neutrino

/// The hub's golden, `hub/tests/web/channel_schema.json`, read by its path in the repository, and a check of a
/// JSON value against one of its models for the parts of JSON Schema pydantic writes.
enum GoldenSchema {
    /// The golden, read once.
    static let golden: [String: JSONValue] = {
        var directory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        for _ in 0..<6 {
            let candidate = directory.appendingPathComponent("hub/tests/web/channel_schema.json")
            if let data = try? Data(contentsOf: candidate), let object = (try? JSONValue.parse(data))?.objectValue {
                return object
            }
            directory = directory.deletingLastPathComponent()
        }
        XCTFail("hub/tests/web/channel_schema.json is not above \(#filePath)")
        return [:]
    }()

    /// The protocol number the golden pins.
    static var protocolNumber: Int? { golden.number("protocol") }

    /// The property names of one model, or of one of its definitions.
    ///
    /// - Parameter name: The model or definition.
    /// - Returns: The names.
    static func properties(_ name: String) -> Set<String> {
        Set(definition(name).object("properties").keys)
    }

    /// Every way a value breaks a model; a field the model does not name is a break.
    ///
    /// - Parameters:
    ///   - value: The value.
    ///   - name: The model.
    /// - Returns: One line per break; empty when the value conforms.
    static func problems(_ value: JSONValue, _ name: String) -> [String] {
        let schema = golden.object("models").object(name)
        return check(value, schema, root: schema, path: name)
    }

    private static func definition(_ name: String) -> [String: JSONValue] {
        let models = golden.object("models")
        if let model = models[name]?.objectValue { return model }
        for model in models.values {
            if let found = model.objectValue?.object("$defs")[name]?.objectValue { return found }
        }
        return [:]
    }

    private static func check(
        _ value: JSONValue, _ schema: [String: JSONValue], root: [String: JSONValue], path: String
    )
        -> [String]
    {
        if let ref = schema["$ref"]?.stringValue {
            let name = String(ref.split(separator: "/").last ?? "")
            let target = root.object("$defs")[name]?.objectValue ?? definition(name)
            return check(value, target, root: root, path: path)
        }
        if let options = schema["anyOf"]?.arrayValue {
            let fits = options.contains { check(value, $0.objectValue ?? [:], root: root, path: path).isEmpty }
            return fits ? [] : ["\(path) matches none of anyOf"]
        }
        switch schema.text("type") {
        case "object":
            guard let object = value.objectValue else { return ["\(path) is not an object"] }
            let properties = schema.object("properties")
            var found: [String] = []
            for required in schema["required"]?.arrayValue?.compactMap(\.stringValue) ?? []
            where object[required] == nil {
                found.append("\(path).\(required) is missing")
            }
            for (key, field) in object {
                if let property = properties[key]?.objectValue {
                    found += check(field, property, root: root, path: "\(path).\(key)")
                } else if !properties.isEmpty {
                    found.append("\(path).\(key) is not in the model")
                }
            }
            return found
        case "array":
            guard let items = value.arrayValue else { return ["\(path) is not an array"] }
            guard let itemSchema = schema["items"]?.objectValue else { return [] }
            return items.enumerated().flatMap { check($1, itemSchema, root: root, path: "\(path)[\($0)]") }
        case "string":
            return value.stringValue == nil ? ["\(path) is not a string"] : []
        case "integer":
            if case .int = value { return [] }
            return ["\(path) is not an integer"]
        case "boolean":
            return value.boolValue == nil ? ["\(path) is not a boolean"] : []
        case "null":
            return value == .null ? [] : ["\(path) is not null"]
        default:
            return []
        }
    }
}
