import Foundation

/// The seam the RustDesk core plugs into: it decodes the machine's screen into frames for a sink and takes the
/// phone's touches and keys. The viewer is written against this and nothing else. Call it on the main queue.
protocol RemoteDesktopCore: AnyObject {
    /// Connect to a shared desktop. Every callback runs on the main queue.
    ///
    /// - Parameters:
    ///   - target: Where it answers, with its seat password and the codec and quality to ask for.
    ///   - onState: Called with each change of the connection.
    ///   - onFrameSize: Called with the remote picture's width and height when they change.
    ///   - onClipboard: Called with text copied on the remote machine.
    func connect(
        target: RemoteDesktopTarget, onState: @escaping (RemoteDesktopState) -> Void,
        onFrameSize: @escaping (Int, Int) -> Void, onClipboard: @escaping (String) -> Void)

    /// Hand the frames to this sink from now on; a sink asks the machine for a fresh keyframe.
    ///
    /// - Parameter sink: The sink, or nil to hand the frames to nothing.
    func attach(_ sink: RemoteDesktopFrameSink?)

    /// A mouse event in the remote picture's pixels.
    ///
    /// - Parameter event: The event.
    func mouse(_ event: RemoteDesktopMouse)

    /// A key pressed or released, by RustDesk's name for it.
    ///
    /// - Parameters:
    ///   - code: The key's name, such as `VK_ESCAPE`.
    ///   - isDown: Whether it is pressed.
    func key(_ code: String, isDown: Bool)

    /// Text typed on the phone's keyboard.
    ///
    /// - Parameter text: The text.
    func type(_ text: String)

    /// Put text on the remote machine's clipboard.
    ///
    /// - Parameter text: The text.
    func clipboard(_ text: String)

    /// Close the connection.
    func disconnect()
}
