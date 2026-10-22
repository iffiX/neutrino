import Foundation

/// One file being read or written, as its row shows it.
struct ShareTransfer: Equatable {
    /// What it does.
    let kind: ShareTransferKind

    /// The file in the share: the one read, or the name the write took.
    let path: SharePath

    /// The name the person asked for, which an upload numbers when the folder holds it.
    let askedName: String

    /// For an upload, the copy in the app's temporary directory it reads from; nil until the copy is made.
    var source: URL?

    /// The bytes moved so far.
    var done: Int64 = 0

    /// The file's size; 0 while it is not known.
    var total: Int64 = 0

    /// The code it ended in, `share_interrupted` when the background's close cut it; nil while it runs or waits.
    var error: ClientError?

    /// Whether it waits for the transfer before it to end.
    var isWaiting = false

    /// Whether an upload has written a part of its file into the share.
    var hasWrittenPart = false

    /// Whether it runs or waits for its turn.
    var isRunning: Bool { error == nil }
}
