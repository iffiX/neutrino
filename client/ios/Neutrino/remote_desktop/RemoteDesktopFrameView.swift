import UIKit

/// The view the remote picture is drawn in: its renderer's layer fills it.
final class RemoteDesktopFrameView: UIView {
    /// What the core hands the frames to.
    let renderer = RemoteDesktopFrameRenderer()

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        isUserInteractionEnabled = false
        layer.addSublayer(renderer.display)
    }

    required init?(coder: NSCoder) {
        return nil
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        renderer.display.frame = bounds
        CATransaction.commit()
    }
}
