import SwiftUI
import UniformTypeIdentifiers

struct SettingsDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }
    var data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else {
            throw SettingsError.invalid("The selected item is not a JSON file.")
        }
        self.data = data
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}

@MainActor
struct SettingsView: View {
    @ObservedObject var settings: SettingsStore
    @State private var importing = false
    @State private var exporting = false
    @State private var preparingExport = false
    @State private var document = SettingsDocument(data: Data())
    @State private var message: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button("Export JSON") {
                        let snapshot = settings.value
                        preparingExport = true
                        Task { @MainActor in
                            defer { preparingExport = false }
                            do {
                                let data = try await Task.detached(priority: .utility) {
                                    try snapshot.encoded()
                                }.value
                                document = SettingsDocument(data: data)
                                exporting = true
                            } catch { message = error.localizedDescription }
                        }
                    }
                    .disabled(preparingExport || settings.loadState == .loading)
                    Button("Import JSON") { importing = true }
                } header: {
                    Text("Configuration")
                } footer: {
                    Text("Server and Background settings, the Start/Stop choice and the last tab are saved automatically. Changes take effect before saving finishes. Import applies the complete configuration after it is saved, restarting the server if needed.")
                }
                Section {
                    Text("Exported JSON includes the authentication password in plain text. Keep the file private and only import trusted configurations.")
                    Text("Enabled services resume when you open the app. iOS does not let the app relaunch itself after termination.")
                }
                .font(.footnote)
                if let error = settings.errorMessage {
                    Section("Storage error") {
                        Text(error)
                        Button("Retry Save") {
                            Task { @MainActor in
                                do { try await settings.flush() }
                                catch { message = error.localizedDescription }
                            }
                        }
                    }
                } else if settings.loadState == .loading {
                    Section { Text("Loading saved settings...") }
                } else if settings.savePending {
                    Section { Text("Saving changes...") }
                }
            }
            .navigationTitle("Settings")
            .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
                Task { @MainActor in
                    do { try await settings.importFile(result.get()) }
                    catch { message = error.localizedDescription }
                }
            }
            .fileExporter(isPresented: $exporting, document: document, contentType: .json,
                          defaultFilename: "Socks5-settings") { result in
                if case .failure(let error) = result { message = error.localizedDescription }
            }
            .alert("Settings", isPresented: Binding(get: { message != nil }, set: { if !$0 { message = nil } })) {
                Button("OK") { message = nil }
            } message: { Text(message ?? "") }
        }
    }
}
