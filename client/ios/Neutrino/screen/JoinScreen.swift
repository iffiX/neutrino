import SwiftUI

/// The Join page: a camera view that scans the hub's QR code, with Scan under it above the bottom bar and in the
/// page header beside the sidebar, and under it the input for the link and Join. A scan and a paste are one path:
/// the link is read and the binding kept at once.
struct JoinScreen: View {
    @ObservedObject var core: ClientCore

    /// Called once a join has kept its binding: the page goes back to the hubs.
    let onJoined: () -> Void

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.isSidebar) private var isSidebar
    @State private var link = ""
    @State private var access = CameraAccess.current
    @State private var scanCount = 0

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard {
                    camera
                        .frame(height: 300)
                        .frame(maxWidth: .infinity)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    if !isSidebar {
                        HStack {
                            Spacer()
                            NeutrinoButton(label: scanAction.label, tier: .primary, isEnabled: scanAction.isEnabled) {
                                scanAction.action()
                            }
                        }
                        .padding(12)
                    }
                }
                SurfaceCard {
                    VStack(alignment: .leading, spacing: 10) {
                        RowText(text: words.word("ui.paste_hint"), style: .note)
                        TextField("neutrino://enroll/…", text: $link, axis: .vertical)
                            .font(.system(size: 13, design: .monospaced))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .lineLimit(1...4)
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 6).fill(palette.elevated))
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(palette.border, lineWidth: 1))
                        HStack {
                            Spacer()
                            NeutrinoButton(
                                label: words.word(core.joining.isJoining ? "ui.job.joining" : "ui.join"),
                                tier: .primary,
                                isBusy: core.joining.isJoining, isEnabled: !link.isEmpty
                            ) { core.join(link) }
                        }
                        if let refusal = core.joining.refusal {
                            RowText(text: words.refusal(refusal), style: .error)
                        }
                    }
                    .padding(16)
                }
            }
            .padding(16)
        }
        .preference(key: PageActionKey.self, value: isSidebar ? scanAction : nil)
        .onChange(of: core.joining.joinedId) { joined in
            guard joined != nil else { return }
            link = ""
            core.clearJoin()
            onJoined()
        }
        .onDisappear { core.clearJoin() }
    }

    @ViewBuilder private var camera: some View {
        switch access {
        case .allowed:
            ZStack(alignment: .bottom) {
                QrScannerView(scanCount: scanCount) { code in core.join(code) }
                RowText(text: words.word("ui.scan_hint"), style: .note)
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 6).fill(palette.surface.opacity(0.85)))
                    .padding(12)
            }
        case .unasked:
            RowText(text: words.word("ui.scan_press"), style: .note).padding(16)
        case .refused:
            RowText(text: words.word("ui.camera_refused"), style: .note).padding(16)
        }
    }

    private var scanAction: PageAction {
        PageAction(
            label: words.word(access == .unasked ? "ui.camera_allow" : "ui.scan"), systemImage: "qrcode.viewfinder",
            isEnabled: access != .refused
        ) {
            switch CameraAccess.current {
            case .unasked:
                CameraAccess.ask { access = $0 }
            case .allowed:
                access = .allowed
                core.clearJoin()
                scanCount += 1
            case .refused:
                access = .refused
            }
        }
    }
}
