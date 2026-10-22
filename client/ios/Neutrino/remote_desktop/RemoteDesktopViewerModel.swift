import Combine
import UIKit

/// What one open viewer holds: its connection's state, where the picture sits, the held keys, the keyboard and the
/// key bar, and the UIKit views of the picture, the fingers and the typing. The core hands the picture to the
/// picture's view while the app is on the screen; a tap clicks, a long press right-clicks, one finger drags, a
/// pinch zooms and moves the picture, two fingers scroll. Text copied on the remote machine goes on the phone's
/// clipboard. Every call runs on the main queue.
final class RemoteDesktopViewerModel: ObservableObject {
    /// Where the connection stands.
    @Published private(set) var state = RemoteDesktopState.connecting

    /// Where the picture sits in the viewer.
    @Published private(set) var viewport = RemoteDesktopViewport()

    /// The key bar's modifiers held for the next key.
    @Published private(set) var held: Set<RemoteDesktopKey> = []

    /// The phone's keyboard.
    @Published private(set) var keyboard = RemoteDesktopKeyboard()

    /// Whether the key bar shows.
    @Published private(set) var isKeyBarShown = false

    /// The desktop shown.
    let target: RemoteDesktopTarget

    /// The view the picture is drawn in.
    let frameView: RemoteDesktopFrameView

    /// The view over the picture that reads the fingers.
    let touchView: RemoteDesktopTouchView

    /// The invisible view the keyboard types into.
    let inputView: RemoteDesktopInputView

    private let core: RemoteDesktopCore
    private let sender: RemoteDesktopInputSender
    private var twoFingers = RemoteDesktopTwoFingers()
    private var keyBarTop: Double?
    private var isOnScreen = true
    private var isStarted = false

    /// Prepare a viewer.
    ///
    /// - Parameters:
    ///   - target: The desktop to show.
    ///   - core: What decodes the picture and sends the input.
    ///   - clock: What paces the typed characters.
    init(target: RemoteDesktopTarget, core: RemoteDesktopCore, clock: ClientClock) {
        self.target = target
        self.core = core
        frameView = RemoteDesktopFrameView(frame: .zero)
        touchView = RemoteDesktopTouchView(frame: .zero)
        inputView = RemoteDesktopInputView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
        let sender = RemoteDesktopInputSender(core: core, platformOs: target.platformOs, clock: clock)
        self.sender = sender
        inputView.connection = RemoteDesktopInputConnection(sender: sender)
        sender.onHeld = { [weak self] keys in self?.held = keys }
        touchView.onTap = { [weak self] point in self?.click(RemoteDesktopMouse.tap, at: point) }
        touchView.onLongPress = { [weak self] point in self?.click(RemoteDesktopMouse.longPress, at: point) }
        touchView.onDragStart = { [weak self] point in self?.click(RemoteDesktopMouse.dragStart, at: point) }
        touchView.onDragMove = { [weak self] point in self?.drag(RemoteDesktopMouse.dragMove, to: point) }
        touchView.onDragEnd = { [weak self] point in self?.drag(RemoteDesktopMouse.dragEnd, to: point) }
        touchView.onTwoFingers = { [weak self] centre, spread in self?.moveTwoFingers(centre, spread: spread) }
        touchView.onTwoFingersEnd = { [weak self] in self?.twoFingers = RemoteDesktopTwoFingers() }
    }

    /// Whether the picture shows, which the touches and the keys wait for.
    var isShowing: Bool { state == .showing }

    /// Connect, and hand the picture to the picture's view.
    func start() {
        guard !isStarted else { return }
        isStarted = true
        core.connect(
            target: target,
            onState: { [weak self] next in self?.state = next },
            onFrameSize: { [weak self] width, height in self?.frameSized(width: width, height: height) },
            onClipboard: { text in UIPasteboard.general.string = text })
        if isOnScreen { core.attach(frameView.renderer) }
    }

    /// The viewer is gone: the picture goes nowhere, the keyboard goes away, and the connection closes.
    func stop() {
        guard isStarted else { return }
        isStarted = false
        core.attach(nil)
        inputView.hideKeyboard()
        sender.close()
        core.disconnect()
    }

    /// The app left the screen or came back: the picture stops, or comes back with a fresh keyframe.
    ///
    /// - Parameter isOnScreen: Whether the app is on the screen.
    func sceneChanged(isOnScreen: Bool) {
        guard isOnScreen != self.isOnScreen else { return }
        self.isOnScreen = isOnScreen
        guard isStarted else { return }
        core.attach(isOnScreen ? frameView.renderer : nil)
    }

    /// The viewer has a new size, as on a rotation: the picture is fitted whole again.
    ///
    /// - Parameter size: The viewer's size in points.
    func sized(_ size: CGSize) {
        viewport = viewport.sized(
            viewWidth: Double(size.width), viewHeight: Double(size.height), frameWidth: viewport.frameWidth,
            frameHeight: viewport.frameHeight)
    }

    /// The keyboard came, went or changed its height: the picture moves to the part above it and the key bar.
    ///
    /// - Parameter keyboard: The keyboard.
    func keyboardChanged(_ keyboard: RemoteDesktopKeyboard) {
        self.keyboard = keyboard
        cover()
    }

    /// The key bar was laid out or went away: the picture moves to the part above it.
    ///
    /// - Parameter top: The key bar's top edge in the viewer, or nil when it is hidden.
    func keyBarPlaced(top: Double?) {
        keyBarTop = top
        cover()
    }

    /// One of the three round buttons was pressed.
    ///
    /// - Parameters:
    ///   - button: The button.
    ///   - onClose: What Close does.
    func press(_ button: RemoteDesktopButton, onClose: () -> Void) {
        button.press(
            keyboard: keyboard, isKeyBarShown: isKeyBarShown,
            onKeyboard: { isUp in isUp ? inputView.showKeyboard() : inputView.hideKeyboard() },
            onKeyBar: { isShown in isKeyBarShown = isShown }, onClose: onClose)
    }

    /// A key of the key bar was pressed.
    ///
    /// - Parameter key: The key.
    func barKey(_ key: RemoteDesktopKey) {
        sender.barKey(key)
    }

    /// The key bar's Paste: the text goes on the remote machine's clipboard and Ctrl+V is pressed there.
    ///
    /// - Parameter text: The phone's clipboard text.
    func paste(_ text: String) {
        sender.paste(text)
    }

    private func cover() {
        viewport = viewport.covering(keyboard.covered(keyBarTop: keyBarTop, viewHeight: viewport.viewHeight))
    }

    private func frameSized(width: Int, height: Int) {
        viewport = viewport.sized(
            viewWidth: viewport.viewWidth, viewHeight: viewport.viewHeight, frameWidth: width, frameHeight: height)
    }

    private func click(_ events: (Int, Int) -> [RemoteDesktopMouse], at point: CGPoint) {
        guard isShowing else { return }
        let pixel = viewport.toFrame(x: Double(point.x), y: Double(point.y))
        for event in events(pixel.x, pixel.y) { core.mouse(event) }
    }

    private func drag(_ event: (Int, Int) -> RemoteDesktopMouse, to point: CGPoint) {
        guard isShowing else { return }
        let pixel = viewport.toFrame(x: Double(point.x), y: Double(point.y))
        core.mouse(event(pixel.x, pixel.y))
    }

    private func moveTwoFingers(_ centre: CGPoint, spread: Double) {
        guard isShowing else { return }
        switch twoFingers.move(centreX: Double(centre.x), centreY: Double(centre.y), spread: spread) {
        case .pinch(let factor, let focusX, let focusY, let dx, let dy):
            viewport = viewport.zoomed(by: factor, focusX: focusX, focusY: focusY).panned(dx: dx, dy: dy)
        case .wheel(let event):
            core.mouse(event)
        case nil:
            break
        }
    }
}
