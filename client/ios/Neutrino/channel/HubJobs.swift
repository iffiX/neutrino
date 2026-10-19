import Foundation

/// The actions running on one hub; a button reads its own job from here and from nowhere else.
struct HubJobs: Equatable {
    /// Whether a refresh waits for the hub's state frame, a code or its 10 s.
    var isRefreshing = false

    /// Whether a leave runs.
    var isLeaving = false

    /// Whether Panel makes the panel's forward and opens the in-app browser.
    var isOpeningPanel = false

    /// Whether any job runs on the hub.
    var isAnyRunning: Bool { isRefreshing || isLeaving || isOpeningPanel }
}
