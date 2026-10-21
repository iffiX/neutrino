import AVFoundation
import CoreMedia
import CoreVideo

/// The sink of the remote picture: each frame the core hands over is copied into a pixel buffer and shown at once
/// by a sample buffer display layer. Frames arrive on the core's thread; a lock keeps them in order with a size
/// change.
final class RemoteDesktopFrameRenderer: RemoteDesktopFrameSink {
    /// The layer the frames are shown in; its owner sizes it.
    let display = AVSampleBufferDisplayLayer()

    private let lock = NSLock()
    private var pool: CVPixelBufferPool?
    private var poolWidth = 0
    private var poolHeight = 0
    private var format: CMVideoFormatDescription?

    /// Make the renderer and its layer.
    init() {
        display.videoGravity = .resize
        display.backgroundColor = CGColor(gray: 0, alpha: 1)
    }

    func draw(bgra: UnsafePointer<UInt8>, width: Int, height: Int, stride: Int) {
        guard width > 0, height > 0, stride >= width * 4 else { return }
        lock.lock()
        defer { lock.unlock() }
        guard let buffer = pixelBuffer(width: width, height: height) else { return }
        CVPixelBufferLockBaseAddress(buffer, [])
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
            let copied = min(width * 4, rowBytes)
            for row in 0..<height {
                (base + row * rowBytes).copyMemory(from: bgra + row * stride, byteCount: copied)
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        guard let sample = sampleBuffer(buffer) else { return }
        if display.status == .failed { display.flush() }
        display.enqueue(sample)
    }

    private func pixelBuffer(width: Int, height: Int) -> CVPixelBuffer? {
        if pool == nil || width != poolWidth || height != poolHeight {
            let attributes: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
                kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any](),
            ]
            var made: CVPixelBufferPool?
            CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &made)
            pool = made
            poolWidth = width
            poolHeight = height
            format = nil
        }
        guard let pool else { return nil }
        var buffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer)
        return buffer
    }

    private func sampleBuffer(_ buffer: CVPixelBuffer) -> CMSampleBuffer? {
        if format == nil {
            var made: CMVideoFormatDescription?
            CMVideoFormatDescriptionCreateForImageBuffer(
                allocator: nil, imageBuffer: buffer, formatDescriptionOut: &made)
            format = made
        }
        guard let format else { return nil }
        var timing = CMSampleTimingInfo(
            duration: .invalid, presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
            decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        CMSampleBufferCreateReadyWithImageBuffer(
            allocator: nil, imageBuffer: buffer, formatDescription: format, sampleTiming: &timing,
            sampleBufferOut: &sample)
        guard let sample else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true)
            as? [NSMutableDictionary]
        {
            attachments.first?[kCMSampleAttachmentKey_DisplayImmediately] = true
        }
        return sample
    }
}
