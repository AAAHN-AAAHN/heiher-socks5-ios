import SwiftUI
import HevSocks5Server

/// Owns the blocking engine call independently of which tab is visible.
@MainActor
final class ServerController: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var status = "Stopped"
    private var current: ServerSettings?
    private var desired: ServerSettings?
    private var stopping = false
    private var attempted: ServerSettings?

    func apply(_ settings: AppSettings, retry: Bool = false) {
        desired = settings.serverRunning ? settings.server : nil
        if desired == nil { attempted = nil }
        if let current {
            if current != desired && !stopping {
                stopping = true
                status = "Stopping"
                hev_socks5_server_quit()
            }
            return
        }
        if desired == nil || retry || desired != attempted { startDesired() }
    }

    private func startDesired() {
        attempted = desired
        guard let desired else { status = "Stopped"; return }
        do {
            let configuration = try desired.configuration()
            current = desired
            isRunning = true
            status = "Running"
            DispatchQueue.global(qos: .utility).async {
                let result = hev_socks5_server_main_from_str(configuration, UInt32(configuration.utf8.count))
                Task { @MainActor in self.finished(result) }
            }
        } catch {
            status = error.localizedDescription
        }
    }

    private func finished(_ result: Int32) {
        let restart = stopping && desired != nil
        current = nil
        isRunning = false
        stopping = false
        status = desired == nil ? "Stopped" : "Server exited (\(result)). Check settings, then press Start."
        if restart { startDesired() }
    }
}
