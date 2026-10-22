import UIKit

@testable import Neutrino

/// A core that shows a drawn desktop: it reports the picture showing at its size as soon as it connects, and hands
/// the picture to every sink attached. The picture is a blue desktop with a red edge and a taskbar along its bottom.
final class PictureRemoteDesktopCore: RemoteDesktopCore {
    /// The picture's width in pixels.
    let width = 1920

    /// The picture's height in pixels.
    let height = 1080

    /// The picture as an image.
    private(set) lazy var picture: UIImage = drawPicture()

    func connect(
        target: RemoteDesktopTarget, onState: @escaping (RemoteDesktopState) -> Void,
        onFrameSize: @escaping (Int, Int) -> Void, onClipboard: @escaping (String) -> Void
    ) {
        onState(.showing)
        onFrameSize(width, height)
    }

    func attach(_ sink: RemoteDesktopFrameSink?) {
        let info = CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        guard let sink, let image = picture.cgImage,
            let context = CGContext(
                data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: info)
        else { return }
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        guard let data = context.data else { return }
        sink.draw(
            bgra: data.assumingMemoryBound(to: UInt8.self), width: width, height: height, stride: context.bytesPerRow)
    }

    func mouse(_ event: RemoteDesktopMouse) {}

    func key(_ code: String, isDown: Bool) {}

    func type(_ text: String) {}

    func clipboard(_ text: String) {}

    func disconnect() {}

    private func drawPicture() -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let size = CGSize(width: width, height: height)
        return UIGraphicsImageRenderer(size: size, format: format).image { drawing in
            let context = drawing.cgContext
            UIColor(red: 0.12, green: 0.36, blue: 0.62, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: size))
            UIColor(white: 0.95, alpha: 1).setFill()
            context.fill(CGRect(x: 240, y: 160, width: 900, height: 560))
            let title: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 64, weight: .semibold), .foregroundColor: UIColor.black,
            ]
            NSString(string: "Remote desktop, top").draw(at: CGPoint(x: 290, y: 200), withAttributes: title)
            UIColor(white: 0.12, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: height - 96, width: width, height: 96))
            UIColor(red: 0.0, green: 0.47, blue: 0.84, alpha: 1).setFill()
            context.fill(CGRect(x: 24, y: height - 84, width: 72, height: 72))
            let bar: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 52, weight: .medium), .foregroundColor: UIColor.white,
            ]
            NSString(string: "Taskbar: the bottom edge").draw(at: CGPoint(x: 130, y: height - 82), withAttributes: bar)
            NSString(string: "14:23").draw(at: CGPoint(x: width - 190, y: height - 82), withAttributes: bar)
            UIColor.red.setStroke()
            context.setLineWidth(12)
            context.stroke(CGRect(origin: .zero, size: size).insetBy(dx: 6, dy: 6))
        }
    }
}
