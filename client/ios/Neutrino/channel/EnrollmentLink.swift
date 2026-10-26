import Compression
import Foundation

/// A client link from a hub's Clients page, pasted, opened or scanned from its QR code:
/// `neutrino://enroll/<base64url>`, one JSON object compressed with zlib, in base64url without padding.
struct EnrollmentLink: Equatable {
    /// Every address the hub answers on, in the hub's order, without a trailing slash.
    let urls: [String]

    /// The enrolment ticket, spent by the join.
    let ticket: String

    /// The hub's static public key, 64 lowercase hex characters.
    let hubKey: String

    /// The hub's virtual networks, whose hub addresses every round dials.
    let overlays: [ChannelOverlay]

    /// Read what a person pasted, opened or scanned.
    ///
    /// - Parameter text: The link, or its bare payload without the scheme.
    /// - Returns: The link.
    /// - Throws: `ClientError.refused` with `link_missing` for nothing, `link_unreadable` for something that is
    ///   not a link, `link_incomplete` for a link without an address, a ticket or the hub's key, and
    ///   `link_not_for_client {role}` for a device's link.
    static func parse(_ text: String) throws -> EnrollmentLink {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { throw ClientError.refusal("link_missing") }
        let payload =
            trimmed.hasPrefix(Channel.linkPrefix) ? String(trimmed.dropFirst(Channel.linkPrefix.count)) : trimmed
        guard let object = decode(payload) else { throw ClientError.refusal("link_unreadable") }
        let urls = cleanUrls(object["urls"])
        let ticket = object.text("token")
        let hubKey = object.text("key").trimmingCharacters(in: .whitespaces).lowercased()
        let role = object.text("role")
        if urls.isEmpty || ticket.isEmpty || !isKey(hubKey) { throw ClientError.refusal("link_incomplete") }
        if role != Client.role { throw ClientError.refusal("link_not_for_client", ["role": role]) }
        return EnrollmentLink(
            urls: urls, ticket: ticket, hubKey: hubKey, overlays: ChannelOverlay.list(object["overlays"]))
    }

    /// A list of addresses as a binding keeps them.
    ///
    /// - Parameter value: What a link or a state carried.
    /// - Returns: Each non-blank string without its trailing slash, in order, each once.
    static func cleanUrls(_ value: JSONValue?) -> [String] {
        var seen = Set<String>()
        var urls: [String] = []
        for item in value?.arrayValue ?? [] {
            guard var url = item.stringValue?.trimmingCharacters(in: .whitespaces) else { continue }
            while url.hasSuffix("/") { url.removeLast() }
            if url.isEmpty || seen.contains(url) { continue }
            seen.insert(url)
            urls.append(url)
        }
        return urls
    }

    /// Inflate a zlib stream (RFC 1950): its two-byte header, the deflated bytes and their Adler-32.
    ///
    /// - Parameter packed: The stream.
    /// - Returns: The bytes, or nil when the stream is not zlib, is cut short or fails its checksum.
    static func inflate(_ packed: Data) -> Data? {
        let bytes = [UInt8](packed)
        guard bytes.count > 6 else { return nil }
        let header = UInt16(bytes[0]) << 8 | UInt16(bytes[1])
        guard bytes[0] & 0x0F == 8, header % 31 == 0, bytes[1] & 0x20 == 0 else { return nil }
        let deflated = Array(bytes[2..<(bytes.count - 4)])
        let trailer = bytes[(bytes.count - 4)...].reduce(UInt32(0)) { $0 << 8 | UInt32($1) }
        var capacity = max(deflated.count * 8, 4096)
        while capacity <= Channel.linkInflatedBytesMax {
            var output = [UInt8](repeating: 0, count: capacity)
            let written = output.withUnsafeMutableBufferPointer { target -> Int in
                deflated.withUnsafeBufferPointer { source -> Int in
                    guard let targetStart = target.baseAddress, let sourceStart = source.baseAddress else { return 0 }
                    return compression_decode_buffer(
                        targetStart, capacity, sourceStart, source.count, nil, COMPRESSION_ZLIB)
                }
            }
            if written == 0 { return nil }
            if written < capacity {
                let inflated = Array(output[0..<written])
                return adler32(inflated) == trailer ? Data(inflated) : nil
            }
            capacity *= 4
        }
        return nil
    }

    private static func decode(_ text: String) -> [String: JSONValue]? {
        var base64 = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        base64 += String(repeating: "=", count: (4 - base64.count % 4) % 4)
        guard let packed = Data(base64Encoded: base64), let inflated = inflate(packed) else { return nil }
        return (try? JSONValue.parse(inflated))?.objectValue
    }

    private static func isKey(_ text: String) -> Bool {
        text.count == Channel.keyHexLength && text.allSatisfy { $0.isHexDigit && !$0.isUppercase }
    }

    private static func adler32(_ bytes: [UInt8]) -> UInt32 {
        var low: UInt32 = 1
        var high: UInt32 = 0
        for byte in bytes {
            low = (low + UInt32(byte)) % 65521
            high = (high + low) % 65521
        }
        return high << 16 | low
    }
}
