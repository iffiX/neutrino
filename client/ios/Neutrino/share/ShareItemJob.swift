import Foundation

/// The job running on a file's or a folder's row, each worded as its in-progress word.
enum ShareItemJob: String {
    /// Rename.
    case renaming = "ui.job.renaming"

    /// Delete.
    case deleting = "ui.job.deleting"
}
