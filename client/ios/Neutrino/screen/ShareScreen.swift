import QuickLook
import SwiftUI
import UniformTypeIdentifiers

/// The time a file's row shows, the same in every language.
private let changedTime: DateFormatter = {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    return formatter
}()

private let byteCount: ByteCountFormatter = {
    let formatter = ByteCountFormatter()
    formatter.countStyle = .file
    formatter.allowsNonnumericFormatting = false
    return formatter
}()

/// The share page: one folder of the open share, its uploads above its folders and files. A tap on a folder
/// opens it and a tap on a file reads it and shows it in the preview; each row's menu holds Rename, Save to
/// Files and Delete, which arms the row; Upload from Files, Upload from Photos and New folder are the page's
/// actions; a pull reads the folder again.
struct ShareScreen: View {
    @ObservedObject var core: ClientCore

    /// The page as the app core holds it.
    let share: ShareView

    @Environment(\.words) private var words
    @Environment(\.palette) private var palette
    @EnvironmentObject private var arm: ArmState
    @State private var isPickingFiles = false
    @State private var isPickingPhotos = false
    @State private var naming: Naming?
    @State private var name = ""

    var body: some View {
        let uploads = share.uploads
        let listed = share.listed
        ScrollView {
            VStack(spacing: 16) {
                SurfaceCard {
                    FeatureRow {
                        RowText(text: "/" + share.path.text, style: .mono)
                        if let error = share.error {
                            RowText(text: words.refusal(error), style: .error)
                        }
                    } actions: {
                        if share.isListing || share.isMakingFolder {
                            ProgressView().controlSize(.small).tint(palette.signalWarn)
                        }
                    }
                }
                if !uploads.isEmpty {
                    SurfaceCard {
                        ForEach(Array(uploads.enumerated()), id: \.element.path) { index, transfer in
                            uploadRow(transfer, hasDivider: index < uploads.count - 1)
                        }
                    }
                }
                SurfaceCard {
                    if listed.isEmpty {
                        FeatureRow {
                            RowText(text: words.word(share.isListing ? "ui.job.opening" : "ui.empty_folder"))
                        } actions: {
                            EmptyView()
                        }
                    } else {
                        ForEach(Array(listed.enumerated()), id: \.element.id) { index, item in
                            itemRow(item, hasDivider: index < listed.count - 1)
                        }
                    }
                }
            }
            .padding(16)
            .sheet(isPresented: $isPickingPhotos) {
                PhotoPickerRepresentable { providers in
                    isPickingPhotos = false
                    guard !providers.isEmpty else { return }
                    core.shares.session?.upload(deliveries: providers.map { SharePhotoDelivery(provider: $0) })
                }
                .ignoresSafeArea()
            }
        }
        .refreshable {
            await MainActor.run { core.shares.pull() }
            while await MainActor.run(body: { core.share?.isListing == true }) {
                try? await Task.sleep(nanoseconds: SharePage.refreshPollNanoseconds)
            }
        }
        .preference(key: PageActionKey.self, value: pageAction)
        .fileImporter(isPresented: $isPickingFiles, allowedContentTypes: [.item], allowsMultipleSelection: true) {
            result in
            if case .success(let urls) = result { core.shares.session?.upload(urls) }
        }
        .quickLookPreview(
            Binding(
                get: { share.preview },
                set: { url in
                    if url == nil { core.shares.session?.closePreview() }
                })
        )
        .sheet(
            isPresented: Binding(
                get: { share.export != nil },
                set: { isShown in
                    if !isShown { core.shares.session?.closeExport() }
                })
        ) {
            if let url = share.export {
                ExportPickerRepresentable(url: url) { core.shares.session?.closeExport() }
            }
        }
        .alert(
            words.word(naming == .folder ? "ui.new_folder" : "ui.rename"),
            isPresented: Binding(
                get: { naming != nil },
                set: { isShown in
                    if !isShown { naming = nil }
                })
        ) {
            TextField(words.word("ui.name_hint"), text: $name)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button(words.word("ui.cancel"), role: .cancel) { naming = nil }
            Button(words.word(naming == .folder ? "ui.create" : "ui.rename")) { commitName() }
                .disabled(!ShareName.isValid(name))
        }
    }

    private var pageAction: PageAction {
        PageAction(
            label: words.word("ui.add"), systemImage: "plus", isEnabled: share.isConnected, action: {},
            items: [
                PageAction(
                    label: words.word("ui.upload_from_files"), systemImage: "folder", isEnabled: true
                ) {
                    isPickingFiles = true
                },
                PageAction(
                    label: words.word("ui.upload_from_photos"), systemImage: "photo.on.rectangle", isEnabled: true
                ) {
                    isPickingPhotos = true
                },
                PageAction(
                    label: words.word("ui.new_folder"), systemImage: "folder.badge.plus",
                    isEnabled: !share.isMakingFolder
                ) {
                    name = ""
                    naming = .folder
                },
            ])
    }

    @ViewBuilder
    private func itemRow(_ item: ShareItem, hasDivider: Bool) -> some View {
        let key = share.path.child(item.name).text
        let transfer = share.transfers[key]
        let job = share.jobs[key]
        let armKey = "delete-\(share.target.id)/\(key)"
        FeatureRow(hasDivider: hasDivider) {
            HStack(spacing: 8) {
                Image(systemName: item.isFolder ? "folder.fill" : "doc")
                    .foregroundColor(item.isFolder ? palette.accent : palette.textMuted)
                RowText(text: item.name, style: .title)
            }
            if let line = stateLine(item, transfer: transfer, job: job) {
                RowText(text: line, style: .note)
            }
            if let transfer, transfer.isRunning {
                progress(transfer)
            }
            if let error = transfer?.error ?? share.errors[key] {
                RowText(text: words.refusal(error), style: .error)
            }
        } actions: {
            if let transfer {
                transferActions(transfer, key: key)
            } else if arm.armed == armKey {
                ArmedButton(
                    key: armKey, label: words.word("ui.delete"), armedLabel: words.word("ui.delete_armed"),
                    isEnabled: job == nil
                ) { core.shares.session?.delete(item) }
            } else {
                menu(item, armKey: armKey, isEnabled: job == nil && share.isConnected)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { tap(item, isFree: transfer?.isRunning != true && job == nil) }
    }

    private func uploadRow(_ transfer: ShareTransfer, hasDivider: Bool) -> some View {
        FeatureRow(hasDivider: hasDivider) {
            HStack(spacing: 8) {
                Image(systemName: "arrow.up.doc").foregroundColor(palette.textMuted)
                RowText(text: transfer.path.name, style: .title)
            }
            RowText(text: transferLine(transfer), style: .note)
            if transfer.isRunning {
                progress(transfer)
            }
            if let error = transfer.error {
                RowText(text: words.refusal(error), style: .error)
            }
        } actions: {
            transferActions(transfer, key: transfer.path.text)
        }
    }

    @ViewBuilder
    private func transferActions(_ transfer: ShareTransfer, key: String) -> some View {
        if !transfer.isRunning {
            NeutrinoButton(label: words.word("ui.retry"), isEnabled: share.isConnected) {
                core.shares.session?.retry(key)
            }
        }
        NeutrinoButton(label: words.word("ui.cancel"), tier: .ghost) { core.shares.session?.cancel(key) }
    }

    private func menu(_ item: ShareItem, armKey: String, isEnabled: Bool) -> some View {
        Menu {
            Button {
                name = item.name
                naming = .rename(item)
            } label: {
                Label(words.word("ui.rename"), systemImage: "pencil")
            }
            if !item.isFolder {
                Button {
                    core.shares.session?.save(item)
                } label: {
                    Label(words.word("ui.save_to_files"), systemImage: "square.and.arrow.down")
                }
            }
            Button(role: .destructive) {
                arm.arm(armKey)
            } label: {
                Label(words.word("ui.delete"), systemImage: "trash")
            }
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.system(size: 18))
                .foregroundColor(isEnabled ? palette.text : palette.textFaint)
                .frame(width: 32, height: 28)
        }
        .disabled(!isEnabled)
        .accessibilityLabel(words.word("ui.more"))
    }

    private func progress(_ transfer: ShareTransfer) -> some View {
        ProgressView(value: transfer.total > 0 ? min(Double(transfer.done) / Double(transfer.total), 1) : 0)
            .tint(palette.accent)
    }

    private func stateLine(_ item: ShareItem, transfer: ShareTransfer?, job: ShareItemJob?) -> String? {
        if let transfer { return transferLine(transfer) }
        if let job { return words.word(job.rawValue) }
        guard !item.isFolder else { return nil }
        let size = byteCount.string(fromByteCount: item.size)
        guard let modified = item.modified else { return size }
        return size + " · " + changedTime.string(from: modified)
    }

    private func transferLine(_ transfer: ShareTransfer) -> String {
        let word = words.word(transfer.kind.rawValue)
        guard transfer.total > 0 else { return word }
        let amount = words.word(
            "ui.share_progress",
            [
                "done": byteCount.string(fromByteCount: transfer.done),
                "total": byteCount.string(fromByteCount: transfer.total),
            ])
        return word + " · " + amount
    }

    private func tap(_ item: ShareItem, isFree: Bool) {
        guard isFree, share.isConnected else { return }
        if item.isFolder {
            core.shares.session?.enter(item)
        } else {
            core.shares.session?.open(item)
        }
    }

    private func commitName() {
        guard let naming else { return }
        self.naming = nil
        switch naming {
        case .folder: core.shares.session?.makeFolder(name)
        case .rename(let item): core.shares.session?.rename(item, to: name)
        }
    }

    /// What the name dialog names.
    private enum Naming: Equatable {
        /// A new folder in the folder shown.
        case folder

        /// A new name for a file or a folder.
        case rename(ShareItem)
    }
}
