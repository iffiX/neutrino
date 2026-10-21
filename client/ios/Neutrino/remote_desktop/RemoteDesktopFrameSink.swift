import Foundation

/// What the core hands each decoded frame of the remote screen to.
protocol RemoteDesktopFrameSink: AnyObject {
    /// Take one frame. Called on the core's own thread, one frame at a time; the bytes are valid only during the
    /// call.
    ///
    /// - Parameters:
    ///   - bgra: The pixels, four bytes each in the order blue, green, red, alpha, row after row.
    ///   - width: The frame's width in pixels.
    ///   - height: The frame's height in pixels.
    ///   - stride: The bytes from the start of one row to the start of the next.
    func draw(bgra: UnsafePointer<UInt8>, width: Int, height: Int, stride: Int)
}
