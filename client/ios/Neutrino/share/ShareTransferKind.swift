import Foundation

/// What a transfer does, each worded as its row's in-progress word.
enum ShareTransferKind: String {
    /// A tap on a file: it is read, then the preview shows it.
    case open = "ui.job.opening"

    /// Save to Files: the file is read, then the export picker saves it.
    case save = "ui.job.downloading"

    /// Upload: a picked file is written into the folder.
    case upload = "ui.job.uploading"
}
