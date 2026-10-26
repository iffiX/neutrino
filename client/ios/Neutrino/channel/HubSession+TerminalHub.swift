import Foundation

extension HubSession: TerminalHub {
    func openShell(_ open: [String: JSONValue]) -> Result<TransportStream, ClientError> {
        openStream(open, carriage: .records)
    }
}
