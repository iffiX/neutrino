import SwiftUI
import UIKit

/// The viewer over the whole screen, with the status bar and the home indicator hidden: the remote picture, and
/// three round buttons at the top right that always stay. Keyboard raises or puts away the phone's keyboard, Keys
/// shows or hides a row of keys a phone keyboard lacks with Paste beside them, Close ends the session; the
/// keyboard and the key bar start off. The key bar sits right above the keyboard, and the picture keeps its size
/// and moves to the part of the screen above them. Until the picture shows, its place holds a spinner or the
/// reason it stopped.
struct RemoteDesktopViewer: View {
    /// What Close does.
    let onClose: () -> Void

    @StateObject private var model: RemoteDesktopViewerModel
    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @Environment(\.scenePhase) private var scenePhase

    /// Open a viewer.
    ///
    /// - Parameters:
    ///   - target: The desktop to show.
    ///   - core: What decodes the picture and sends the input.
    ///   - onClose: What Close does.
    init(target: RemoteDesktopTarget, core: RemoteDesktopCore, onClose: @escaping () -> Void) {
        self.init(
            model: RemoteDesktopViewerModel(target: target, core: core, clock: SystemClientClock()), onClose: onClose)
    }

    /// Open a viewer on a viewer's model.
    ///
    /// - Parameters:
    ///   - model: What the viewer holds.
    ///   - onClose: What Close does.
    init(model: @autoclosure @escaping () -> RemoteDesktopViewerModel, onClose: @escaping () -> Void) {
        self.onClose = onClose
        _model = StateObject(wrappedValue: model())
    }

    var body: some View {
        ZStack {
            GeometryReader { geometry in
                picture
                    .onAppear {
                        model.sized(geometry.size)
                        model.start()
                    }
                    .onChange(of: geometry.size) { size in model.sized(size) }
            }
            .ignoresSafeArea()
            controls.ignoresSafeArea(.keyboard)
        }
        .background(Color.black.ignoresSafeArea())
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .onDisappear { model.stop() }
        .onChange(of: scenePhase) { phase in model.sceneChanged(isOnScreen: phase != .background) }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) {
            note in
            guard let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            model.keyboardChanged(RemoteDesktopKeyboard.of(frame: frame, viewHeight: model.viewport.viewHeight))
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            model.keyboardChanged(RemoteDesktopKeyboard())
        }
    }

    private var picture: some View {
        let viewport = model.viewport
        return ZStack(alignment: .topLeading) {
            Color.black
            RemoteDesktopHostedView(view: model.frameView)
                .frame(width: viewport.drawnWidth, height: viewport.drawnHeight)
                .offset(x: viewport.left, y: viewport.top)
            RemoteDesktopHostedView(view: model.inputView).frame(width: 1, height: 1)
            RemoteDesktopHostedView(view: model.touchView)
            standing
        }
        .clipped()
    }

    @ViewBuilder private var standing: some View {
        switch model.state {
        case .connecting:
            ProgressView()
                .tint(palette.signalWarn)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .showing:
            EmptyView()
        case .stopped(let refusal):
            Text(words.refusal(refusal))
                .font(.system(size: 13))
                .foregroundColor(palette.textMuted)
                .multilineTextAlignment(.center)
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var controls: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Spacer()
                    ForEach(RemoteDesktopButton.allCases) { button in roundButton(button) }
                }
                .padding(.top, 6)
                .padding(.trailing, 12)
                Spacer()
                if model.isShowing && model.isKeyBarShown {
                    keyBar
                        .background {
                            GeometryReader { bar in
                                Color.clear.preference(
                                    key: RemoteDesktopKeyBarTopKey.self, value: Double(bar.frame(in: .global).minY))
                            }
                        }
                        .padding(.bottom, max(model.keyboard.height - geometry.safeAreaInsets.bottom, 0))
                }
            }
        }
        .onPreferenceChange(RemoteDesktopKeyBarTopKey.self) { top in model.keyBarPlaced(top: top) }
    }

    private func roundButton(_ button: RemoteDesktopButton) -> some View {
        let isActive = button.isActive(keyboard: model.keyboard, isKeyBarShown: model.isKeyBarShown)
        let isEnabled = model.isShowing || button == .close
        let tone = button.isDanger ? palette.error : isActive ? palette.accent : palette.text
        return Button {
            model.press(button, onClose: onClose)
        } label: {
            Image(systemName: button.systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(tone)
                .frame(width: 36, height: 36)
                .background(Circle().fill(palette.surface.opacity(0.6)))
                .background(Circle().fill(isActive ? palette.accentWash : .clear))
                .overlay(
                    Circle().stroke(
                        isActive || button.isDanger ? tone : palette.borderStrong.opacity(0.6), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.4)
        .accessibilityLabel(words.word(button.wordKey))
    }

    private var keyBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(RemoteDesktopKey.allCases) { key in barKey(key, isHeld: model.held.contains(key)) }
                PasteButton(payloadType: String.self) { texts in
                    let text = texts.first ?? ""
                    DispatchQueue.main.async { model.paste(text) }
                }
                .labelStyle(.titleOnly)
                .buttonBorderShape(.roundedRectangle)
                .tint(palette.accent)
            }
            .padding(8)
        }
        .background(palette.elevated)
    }

    private func barKey(_ key: RemoteDesktopKey, isHeld: Bool) -> some View {
        Button {
            model.barKey(key)
        } label: {
            Text(key.label)
                .font(.system(size: 13, design: .monospaced))
                .foregroundColor(isHeld ? palette.accent : palette.text)
                .padding(.horizontal, 12)
                .frame(minHeight: 34)
                .background(RoundedRectangle(cornerRadius: 6).fill(isHeld ? palette.accentWash : palette.surface))
                .overlay(
                    RoundedRectangle(cornerRadius: 6).stroke(
                        isHeld ? palette.accent : palette.borderStrong, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}
