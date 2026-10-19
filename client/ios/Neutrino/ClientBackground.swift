import UIKit

/// The app's time in the background: on leaving the screen it starts a background task and keeps every
/// connection for the time iOS gives it; before that time ends it closes every channel and stops every
/// forward's listener, and returning to the screen brings them back at once.
final class ClientBackground {
    private let core: ClientCore
    private var task = UIBackgroundTaskIdentifier.invalid
    private var closing: DispatchWorkItem?
    private var isSuspended = false

    /// Follow the app's time in the background for one app core.
    ///
    /// - Parameter core: The app core.
    init(core: ClientCore) {
        self.core = core
    }

    /// The app left the screen.
    func entered() {
        guard task == .invalid else { return }
        task = UIApplication.shared.beginBackgroundTask { [weak self] in self?.close() }
        guard task != .invalid else {
            close()
            return
        }
        let remaining = UIApplication.shared.backgroundTimeRemaining
        let seconds = remaining < Background.taskSecondsMax ? remaining : Background.taskSecondsAssumed
        let delay = max(seconds - Background.closeMarginSeconds, 0)
        let item = DispatchWorkItem { [weak self] in self?.close() }
        closing = item
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: item)
    }

    /// The app came back to the screen.
    func returned() {
        closing?.cancel()
        closing = nil
        isSuspended = false
        core.foreground()
        endTask()
    }

    private func close() {
        closing?.cancel()
        closing = nil
        if !isSuspended {
            isSuspended = true
            core.suspend()
        }
        endTask()
    }

    private func endTask() {
        guard task != .invalid else { return }
        UIApplication.shared.endBackgroundTask(task)
        task = .invalid
    }
}
