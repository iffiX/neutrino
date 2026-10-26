import Compression
import Foundation

@testable import Neutrino

/// The bindings, machines and frames the tests share.
enum Samples {
    static let hubKey = String(repeating: "ab", count: 32)

    static let privateKey = String(repeating: "cd", count: 32)

    static let machine = ClientMachine(
        machineId: "0123456789abcdef0123456789abcdef",  // scan: allow
        hostname: "iPhone", arch: "arm64", osVersion: "16.7", version: "0.6.0")

    static let binding = HubBinding(
        id: "b1", name: "iPhone", hubId: "hub-1", hubName: "Home", gatewayUrl: "tcp://192.168.1.1:8443",
        gatewayUrls: ["tcp://192.168.1.1:8443", "tcp://203.0.113.7:8443"], hubKey: hubKey, privateKey: privateKey,
        token: "secret-token")

    static let device = ClientDevice(name: "iPhone", arch: "arm64", osVersion: "16.7", appVersion: "0.6.0")

    /// A welcome frame from the hub.
    static let welcome: [String: JSONValue] = [
        "type": .string("welcome"), "protocol": .int(4), "role": .string("hub"), "id": .string("hub-1"),
        "name": .string("Home"), "software": .string("neutrino_hub/0.6.0"),
    ]

    /// A state frame from the hub.
    ///
    /// - Parameters:
    ///   - hash: The state's hash.
    ///   - extra: Sections beside the hash.
    /// - Returns: The frame.
    static func state(hash: String = "h1", _ extra: [String: JSONValue] = [:]) -> [String: JSONValue] {
        var frame: [String: JSONValue] = ["type": .string("state"), "hash": .string(hash)]
        frame.merge(extra) { _, new in new }
        return frame
    }

    /// A client link as the hub's Clients page writes it: the object as JSON, zlib, base64url without padding.
    ///
    /// - Parameter object: The link's object.
    /// - Returns: `neutrino://enroll/<payload>`.
    static func link(_ object: [String: JSONValue]) -> String {
        let json = [UInt8](JSONValue.object(object).encoded())
        var deflated = [UInt8](repeating: 0, count: json.count + 64)
        let size = deflated.withUnsafeMutableBufferPointer { target -> Int in
            json.withUnsafeBufferPointer { source -> Int in
                guard let targetStart = target.baseAddress, let sourceStart = source.baseAddress else { return 0 }
                return compression_encode_buffer(
                    targetStart, target.count, sourceStart, source.count, nil, COMPRESSION_ZLIB)
            }
        }
        var low: UInt32 = 1
        var high: UInt32 = 0
        for byte in json {
            low = (low + UInt32(byte)) % 65521
            high = (high + low) % 65521
        }
        let adler = high << 16 | low
        let stream =
            [0x78, 0x9C] + deflated[0..<size]
            + [UInt8(adler >> 24), UInt8((adler >> 16) & 0xFF), UInt8((adler >> 8) & 0xFF), UInt8(adler & 0xFF)]
        let base64 = Data(stream).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return Channel.linkPrefix + base64
    }
}
