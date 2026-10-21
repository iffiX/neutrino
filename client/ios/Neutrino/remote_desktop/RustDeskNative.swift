import Foundation

#if NEUTRINO_RUSTDESK
    import RustDeskCore
#endif

/// The RustDesk core's C interface, which `client/ios/rustdesk_core/` declares and only a device build links
/// (`packaging/build/build_core_rustdesk_ios.py`). In a build without it `isLinked` is false and every call does
/// nothing. Call it on the main queue; the callbacks run on the core's threads.
enum RustDeskNative {
    #if NEUTRINO_RUSTDESK
        /// The callbacks of the running session, kept alive until `close` returns.
        private final class SessionBox {
            let callbacks: RustDeskCallbacks

            init(_ callbacks: RustDeskCallbacks) {
                self.callbacks = callbacks
            }
        }

        /// The sink the frames go to, kept alive until another is attached.
        private final class FrameBox {
            let sink: RemoteDesktopFrameSink

            init(_ sink: RemoteDesktopFrameSink) {
                self.sink = sink
            }
        }

        private static var session: SessionBox?
        private static var frames: FrameBox?
    #endif

    /// Whether this build links the core.
    static var isLinked: Bool {
        #if NEUTRINO_RUSTDESK
            return true
        #else
            return false
        #endif
    }

    /// Send the core's log to the app's and set where the core keeps its configuration. Call once.
    ///
    /// - Parameter appDir: A directory of the app's own.
    static func initialize(appDir: String) {
        #if NEUTRINO_RUSTDESK
            nd_set_log(nil) { _, _, text in
                guard let text else { return }
                ClientLog.info("rustdesk: \(String(cString: text))")
            }
            nd_init(appDir)
        #endif
    }

    /// Keep a session option for every later `start`.
    ///
    /// - Parameters:
    ///   - name: RustDesk's name: `image-quality`, or a peer option such as `codec-preference`.
    ///   - value: Its value; empty removes a peer option.
    static func setOption(_ name: String, _ value: String) {
        #if NEUTRINO_RUSTDESK
            nd_set_option(name, value)
        #endif
    }

    /// Connect straight to a machine's RustDesk.
    ///
    /// - Parameters:
    ///   - peer: The machine's address.
    ///   - port: Its direct port.
    ///   - password: Its seat password.
    ///   - callbacks: What the core reports to.
    /// - Returns: 0, or -1 while another session runs or when no core is linked.
    static func start(peer: String, port: Int, password: String, callbacks: RustDeskCallbacks) -> Int {
        #if NEUTRINO_RUSTDESK
            let box = SessionBox(callbacks)
            let handlers = NdCallbacks(
                context: Unmanaged.passUnretained(box).toOpaque(),
                on_state: { context, state, text in
                    guard let context else { return }
                    let box = Unmanaged<SessionBox>.fromOpaque(context).takeUnretainedValue()
                    box.callbacks.onState(Int(state), text.map { String(cString: $0) } ?? "")
                },
                on_size: { context, width, height in
                    guard let context else { return }
                    let box = Unmanaged<SessionBox>.fromOpaque(context).takeUnretainedValue()
                    box.callbacks.onSize(Int(width), Int(height))
                },
                on_clipboard: { context, text in
                    guard let context, let text else { return }
                    let box = Unmanaged<SessionBox>.fromOpaque(context).takeUnretainedValue()
                    box.callbacks.onClipboard(String(cString: text))
                })
            let started = nd_start(peer, Int32(port), password, handlers)
            if started == 0 { session = box }
            return Int(started)
        #else
            return -1
        #endif
    }

    /// Hand every frame to a sink, or to nothing; a sink asks the machine for a fresh keyframe, and no frame
    /// reaches the previous sink after this returns.
    ///
    /// - Parameter sink: The sink, or nil.
    static func attachFrames(_ sink: RemoteDesktopFrameSink?) {
        #if NEUTRINO_RUSTDESK
            guard let sink else {
                nd_attach_frames(nil, nil)
                frames = nil
                return
            }
            let box = FrameBox(sink)
            nd_attach_frames(Unmanaged.passUnretained(box).toOpaque()) { context, bgra, width, height, stride in
                guard let context, let bgra else { return }
                Unmanaged<FrameBox>.fromOpaque(context).takeUnretainedValue().sink.draw(
                    bgra: bgra, width: Int(width), height: Int(height), stride: Int(stride))
            }
            frames = box
        #endif
    }

    /// A mouse event.
    ///
    /// - Parameter event: The column or the horizontal wheel steps, the row or the vertical ones, and the mask.
    static func mouse(_ event: RemoteDesktopMouse) {
        #if NEUTRINO_RUSTDESK
            nd_mouse(Int32(event.x), Int32(event.y), Int32(event.mask))
        #endif
    }

    /// A key by RustDesk's name.
    ///
    /// - Parameters:
    ///   - code: The name.
    ///   - isDown: Whether it is pressed.
    static func key(_ code: String, isDown: Bool) {
        #if NEUTRINO_RUSTDESK
            nd_key(code, isDown)
        #endif
    }

    /// Typed text.
    ///
    /// - Parameter text: The text.
    static func text(_ text: String) {
        #if NEUTRINO_RUSTDESK
            nd_text(text)
        #endif
    }

    /// Text for the remote machine's clipboard.
    ///
    /// - Parameter text: The text.
    static func clipboard(_ text: String) {
        #if NEUTRINO_RUSTDESK
            nd_clipboard(text)
        #endif
    }

    /// End the session; no callback runs after this returns.
    static func close() {
        #if NEUTRINO_RUSTDESK
            nd_close()
            session = nil
        #endif
    }
}
