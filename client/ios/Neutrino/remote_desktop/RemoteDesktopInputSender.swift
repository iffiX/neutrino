import Foundation

/// The viewer's keys and text on their way to the core, with the key bar's modifiers held for one key: Ctrl, Shift,
/// Alt and Win stay down from their press until the next key or text is sent. Every call joins one queue sent in
/// order, and typed text goes one character at a time, `RemoteDesktop.typePaceSeconds` apart; text with any
/// character outside ASCII goes to a Linux host as a paste instead. Every call runs on the main queue.
final class RemoteDesktopInputSender {
    private let core: RemoteDesktopCore
    private let platformOs: String
    private let clock: ClientClock
    private var queue: [() -> Double] = []
    private var isWaiting = false
    private var isClosed = false

    /// Called with the held modifiers each time they change.
    var onHeld: ((Set<RemoteDesktopKey>) -> Void)?

    /// The modifiers held for the next key.
    private(set) var held: Set<RemoteDesktopKey> = []

    /// Make the queue.
    ///
    /// - Parameters:
    ///   - core: Where the keys and the text go.
    ///   - platformOs: The `platform_os` of the machine sharing the desktop, or empty when the entry names none.
    ///   - clock: What paces the typed characters.
    init(core: RemoteDesktopCore, platformOs: String, clock: ClientClock) {
        self.core = core
        self.platformOs = platformOs
        self.clock = clock
    }

    /// Press and release one key, then release the held modifiers.
    ///
    /// - Parameter code: RustDesk's name for the key.
    func press(_ code: String) {
        enqueue { [weak self] in
            self?.sendPress(code)
            return 0
        }
    }

    /// A key of the key bar: a modifier is held or let go, any other key is pressed.
    ///
    /// - Parameter key: The key.
    func barKey(_ key: RemoteDesktopKey) {
        enqueue { [weak self] in
            self?.sendBarKey(key)
            return 0
        }
    }

    /// Text the keyboard committed. A line break is Enter, a tab is Tab, a single letter or digit with a modifier
    /// held is that key, and text with any character outside ASCII to a Linux host is put on its clipboard and
    /// pasted with Shift+Insert; anything else is typed one character at a time.
    ///
    /// - Parameter text: The text.
    func type(_ text: String) {
        guard !text.isEmpty else { return }
        let code = text.count == 1 ? text.first.flatMap(RemoteDesktopKey.code(of:)) : nil
        if text == "\n" {
            press(RemoteDesktopKey.enter)
        } else if text == "\t" {
            press(RemoteDesktopKey.tab.code)
        } else if let code {
            enqueue { [weak self] in
                guard let self else { return 0 }
                if self.held.isEmpty { self.core.type(text) } else { self.sendPress(code) }
                self.release()
                return 0
            }
        } else if platformOs == RemoteDesktop.platformOsLinux,
            text.unicodeScalars.contains(where: { $0.value > RemoteDesktop.asciiLast })
        {
            enqueue { [weak self] in
                self?.sendShiftInsert(text)
                return 0
            }
        } else {
            let characters = Array(text)
            for (index, character) in characters.enumerated() {
                let isLast = index == characters.count - 1
                enqueue { [weak self] in
                    self?.core.type(String(character))
                    if isLast { self?.release() }
                    return isLast ? 0 : RemoteDesktop.typePaceSeconds
                }
            }
        }
    }

    /// Put text on the remote machine's clipboard and press Ctrl+V there.
    ///
    /// - Parameter text: The text; nothing is sent when it is empty.
    func paste(_ text: String) {
        guard !text.isEmpty else { return }
        enqueue { [weak self] in
            self?.sendPaste(text)
            return 0
        }
    }

    /// Stop the queue: what is queued is still sent, later calls send nothing.
    func close() {
        isClosed = true
    }

    private func enqueue(_ step: @escaping () -> Double) {
        guard !isClosed else { return }
        queue.append(step)
        drain()
    }

    private func drain() {
        while !isWaiting, !queue.isEmpty {
            let wait = queue.removeFirst()()
            if wait > 0 {
                isWaiting = true
                clock.schedule(after: wait) {
                    self.isWaiting = false
                    self.drain()
                }
            }
        }
    }

    private func sendPress(_ code: String) {
        core.key(code, isDown: true)
        core.key(code, isDown: false)
        release()
    }

    private func sendBarKey(_ key: RemoteDesktopKey) {
        if !key.isModifier {
            sendPress(key.code)
        } else if held.contains(key) {
            core.key(key.code, isDown: false)
            hold(held.subtracting([key]))
        } else {
            core.key(key.code, isDown: true)
            hold(held.union([key]))
        }
    }

    private func sendPaste(_ text: String) {
        core.clipboard(text)
        core.key(RemoteDesktopKey.ctrl.code, isDown: true)
        core.key(RemoteDesktopKey.paste, isDown: true)
        core.key(RemoteDesktopKey.paste, isDown: false)
        core.key(RemoteDesktopKey.ctrl.code, isDown: false)
        release()
    }

    private func sendShiftInsert(_ text: String) {
        release()
        core.clipboard(text)
        core.key(RemoteDesktopKey.shift.code, isDown: true)
        core.key(RemoteDesktopKey.insert, isDown: true)
        core.key(RemoteDesktopKey.insert, isDown: false)
        core.key(RemoteDesktopKey.shift.code, isDown: false)
    }

    private func release() {
        for key in held { core.key(key.code, isDown: false) }
        hold([])
    }

    private func hold(_ keys: Set<RemoteDesktopKey>) {
        guard keys != held else { return }
        held = keys
        onHeld?(keys)
    }
}
