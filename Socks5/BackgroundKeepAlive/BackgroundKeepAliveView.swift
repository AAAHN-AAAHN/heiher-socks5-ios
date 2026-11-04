import AVFAudio
import Combine
import SwiftUI

@MainActor
struct BackgroundKeepAliveView: View {
    @ObservedObject var keepAlive: BackgroundKeepAlive
    @ObservedObject var udpEcho: PeriodicUDPEchoModel
    @Binding var locationEnabled: Bool
    @Binding var audioEnabled: Bool
    var acceptsNewIntent = true

    private enum InputField: Hashable { case destinations, period }
    @FocusState private var focusedInput: InputField?

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
                    Toggle("Periodic UDP Echo", isOn: Binding(get: { udpEcho.enabled },
                                                             set: { udpEcho.setEnabled($0) }))
                        .disabled(!udpEcho.enabled && !acceptsNewIntent)
                        .accessibilityIdentifier("background.udpEcho.enabled")
                    TextField("Destination IP", text: Binding(get: { udpEcho.destinations },
                                                             set: { udpEcho.setDestinations($0) }), axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focusedInput, equals: .destinations)
                        .disabled(!acceptsNewIntent)
                        .accessibilityIdentifier("background.udpEcho.destinations")
                    TextField("Period (ms)", text: Binding(get: { udpEcho.period },
                                                          set: { udpEcho.setPeriod($0) }))
                        .keyboardType(.numberPad)
                        .focused($focusedInput, equals: .period)
                        .disabled(!acceptsNewIntent)
                        .accessibilityIdentifier("background.udpEcho.period")
                    Text(udpEcho.state).font(.footnote)
                        .accessibilityIdentifier("background.udpEcho.state")
                    LabeledContent("Sent") {
                        Text(String(udpEcho.sentCount))
                            .accessibilityIdentifier("background.udpEcho.sentCount")
                    }
                    if let error = udpEcho.storageError {
                        Text(error).font(.footnote)
                        Button("Retry save") { udpEcho.retrySave() }
                    }
                } header: {
                    Text("Periodic UDP Echo")
                } footer: {
                    Text("Sends to UDP port 7 through the SOCKS5 server. Separate destination IPs with commas or newlines. Sending continues without replies.")
                }
                Section {
                    Text("Audio and location are independent of Server Start/Stop. UDP Echo waits for a running SOCKS5 server. Recovery runs only while iOS allows the app to execute.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Background")
            .toolbar {
                if focusedInput != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Done") { focusedInput = nil }
                            .accessibilityIdentifier("background.udpEcho.done")
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
