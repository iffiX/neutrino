import Foundation

/// The code a failure of the share page's SMB client is worded by.
enum ShareRefusal {
    /// Word one failure: the hub's code when the hub refused a `connect` stream of the share's forward, else the
    /// share's answer.
    ///
    /// - Parameters:
    ///   - error: What the SMB client failed with.
    ///   - hubRefusal: The code the hub refused or ended a `connect` stream with since the connection opened, nil
    ///     for none.
    ///   - isCarried: Whether the forward still carries the SMB client's connection; `EPERM` is the share's
    ///     refusal while it does, and the end of the connection after it.
    /// - Returns: The refusal.
    static func of(_ error: Error, hubRefusal: ClientError?, isCarried: Bool) -> ClientError {
        if let refusal = error as? ClientError { return refusal }
        if let hubRefusal { return hubRefusal }
        guard let code = (error as? POSIXError)?.code else { return .refusal("share_unreachable") }
        switch code {
        case .ECONNREFUSED: return .refusal(SharePage.codeLoginRejected)
        case .EACCES, .EROFS: return .refusal("share_access_denied")
        case .EPERM: return .refusal(isCarried ? "share_access_denied" : "share_unreachable")
        case .ENOENT, .ENOTDIR: return .refusal("share_not_found")
        case .EEXIST: return .refusal("share_name_taken")
        default: return .refusal("share_unreachable")
        }
    }
}
