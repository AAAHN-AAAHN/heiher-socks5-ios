import AVFAudio
import Combine
import SwiftUI
import UniformTypeIdentifiers

@MainActor
struct BackgroundKeepAliveView: View {
    @ObservedObject var keepAlive: BackgroundKeepAlive
    @ObservedObject var ping: PeriodicPingModel
    @Binding var locationEnabled: Bool
    @Binding var audioEnabled: Bool
    // Integrated injects its single Settings owner; standalone uses the model's JSON.
    var pingEnabled: Binding<Bool>? = nil
    var pingDestinations: Binding<String>? = nil
    var pingPeriod: Binding<String>? = nil
    var pingStorageState: String? = nil
    @State private var pingImporting = false
    @State private var pingExporting = false
    @State private var pingPreparingExport = false
    @State private var pingDocument = PingDocument(data: Data())
    @State private var pingFileError: String?
    private enum PingField: Hashable { case destinations, period }
    @FocusState private var pingField: PingField?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Loop silent WAV", isOn: $audioEnabled)
                    Text(keepAlive.audioState).font(.footnote)
                        .accessibilityIdentifier("background.audioState")
                    if !keepAlive.audioDetail.isEmpty {
                        Text(keepAlive.audioDetail).font(.footnote)
                            .accessibilityIdentifier("background.audioDetail")
                    }
                } header: {
                    Text("Audio")
                } footer: {
                    Text("Checks playback and retries every 0.5 seconds. Uses finite execution protection during recovery; an unfinished system call is never treated as cancelled. Mixes with other audio.")
                }
                Section {
                    Toggle("Continuous location", isOn: $locationEnabled)
                } header: {
                    Text("Location")
                } footer: {
                    Text("Keeps a standard location session open with approximate accuracy. Updates are scheduled by iOS; coordinates are discarded.")
                }
                Section("Location state") {
                    Text(keepAlive.locationState)
                    LabeledContent("Reads", value: String(keepAlive.readCount))
                    if let date = keepAlive.lastRead {
                        LabeledContent("Last read") { Text(date, format: .dateTime.hour().minute().second()) }
                    }
                    Text("Allow location access in Settings. Precise Location is not required.")
                        .font(.footnote)
                }
                Section {
                    Toggle("Enabled", isOn: pingEnabled ?? Binding(get: { ping.enabled }, set: { ping.setEnabled($0) }))
                        .accessibilityIdentifier("background.pingEnabled")
                    LabeledContent("Destination ip") {
                        TextField("1.1.1.1, 192.168.0.9", text: pingDestinations ?? Binding(
                            get: { ping.destinations }, set: { ping.setDestinations($0) }))
                            .keyboardType(.asciiCapable)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .multilineTextAlignment(.trailing)
                            .accessibilityIdentifier("background.pingDestinations")
                            .focused($pingField, equals: .destinations)
                    }
                    LabeledContent("Period (ms)") {
                        TextField("1000", text: pingPeriod ?? Binding(get: { ping.period }, set: { ping.setPeriod($0) }))
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .accessibilityIdentifier("background.pingPeriod")
                            .focused($pingField, equals: .period)
                    }
                    Text(ping.status).font(.footnote)
                        .accessibilityIdentifier("background.pingState")
                    Text(pingStorageState ?? ping.persistenceState).font(.footnote)
                        .accessibilityIdentifier("background.pingStorageState")
                    if ping.hasOwnStorage {
                        Button("Export ping JSON") {
                            pingPreparingExport = true
                            Task { @MainActor in
                                defer { pingPreparingExport = false }
                                do {
                                    pingDocument = PingDocument(data: try await ping.exportData())
                                    pingExporting = true
                                } catch { pingFileError = error.localizedDescription }
                            }
                        }
                        .disabled(pingPreparingExport || !ping.canExport)
                        Button("Import ping JSON") { pingImporting = true }
                        if ping.storageError != nil {
                            Button("Retry Save") {
                                pingFileError = nil
                                Task { @MainActor in try? await ping.flush() }
                            }
                        }
                    }
                    if let pingFileError { Text(pingFileError).font(.footnote) }
                } header: {
                    Text("Periodic ping")
                } footer: {
                    Text("Sends ICMP to each IP; separate IPs with commas. Invalid input pauses sending. Supports up to 65,536 unique IPs. Settings are saved and restored on relaunch. Runs while iOS allows execution.")
                }
                Section {
                    Text("Background services are independent of Server Start/Stop. Recovery runs only while iOS allows the app to execute.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Background")
            .fileExporter(isPresented: $pingExporting, document: pingDocument,
                          contentType: .json, defaultFilename: "periodic-ping") { result in
                if case .failure(let error) = result { pingFileError = error.localizedDescription }
            }
            .fileImporter(isPresented: $pingImporting, allowedContentTypes: [.json]) { result in
                Task { @MainActor in
                    do { try await ping.importFile(result.get()); pingFileError = nil }
                    catch { pingFileError = error.localizedDescription }
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    if pingField != nil {
                        Button("Done") { pingField = nil }
                            .accessibilityIdentifier("background.pingDone")
                    }
                }
            }
        }
    }
}

/// Root-only location/foreground restoration. Process-level audio notifications
/// are coalesced by the service on the posting thread, not queued through the UI.
@MainActor
struct BackgroundKeepAliveEvents: ViewModifier {
    let keepAlive: BackgroundKeepAlive
    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
                .receive(on: RunLoop.main)) { _ in keepAlive.restore() }
    }
}

/// Standalone backup only. Integrated uses the existing complete Settings document.
private struct PingDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }
    var data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadUnknown) }
        self.data = data
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}
