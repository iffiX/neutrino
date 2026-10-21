import Foundation

/// Where the viewer dials one shared desktop: the entry's forward on this phone's loopback, with the seat password
/// the hub's `service` stream handed over.
struct RemoteDesktopTarget: Equatable, Identifiable {
    /// The entry's key, `<binding>/<entry>`.
    let key: String

    /// What the viewer names: `<hub>:<machine>`.
    let name: String

    /// The loopback address the forward listens on.
    let host: String

    /// The forward's loopback number.
    let port: Int

    /// The seat password of the machine sharing it.
    let password: String

    /// The codec and quality the session asks for.
    var choice = RemoteDesktopChoice()

    /// The `platform_os` the entry carries, or empty when it names none.
    var platformOs = ""

    /// The entry's key, as a presentation keys the viewer.
    var id: String { key }

    /// Read a `service` stream's answer for an `rdp` entry, for a viewer that dials the entry's forward.
    ///
    /// - Parameters:
    ///   - key: The entry's key.
    ///   - name: What the viewer names.
    ///   - answer: The stream's close: `{password}`, or the hub's refusal.
    ///   - localPort: The loopback number the entry's forward listens on.
    /// - Returns: The target, or the hub's refusal.
    static func of(key: String, name: String, answer: Result<[String: JSONValue], ClientError>, localPort: Int)
        -> Result<RemoteDesktopTarget, ClientError>
    {
        answer.map { material in
            RemoteDesktopTarget(
                key: key, name: name, host: Forward.bindHost, port: localPort, password: material.text("password"))
        }
    }
}

extension RemoteDesktopTarget: CustomStringConvertible {
    var description: String { "RemoteDesktopTarget(name: \(name), host: \(host), port: \(port))" }
}
