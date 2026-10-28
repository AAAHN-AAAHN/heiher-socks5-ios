import Foundation
#if canImport(Combine)
import Combine
#endif
import HevSocks5Server

/// Owns the blocking engine call independently of which tab is visible.
@MainActor
final class ServerController: @MainActor ObservableObject {
    struct Run: Equatable {
        let id: UUID
        let settings: ServerSettings
    }

    let objectWillChange = ObservableObjectPublisher()
    private(set) var isRunning = false
    private(set) var status = "Stopped"
    /// The configuration actually passed to this invocation, admitted until Stop.
    /// Listener readiness is established independently by the client's handshake.
    private(set) var run: Run?
    private var current: ServerSettings?
    private var currentID: UUID?
    private var desired: ServerSettings?
    private var stopping = false
    private var attempted: ServerSettings?

    func apply(_ settings: ServerSettings, running: Bool, retry: Bool = false) {
        desired = running ? settings : nil
        if desired == nil { attempted = nil }
        if let current {
            if current != desired && !stopping {
                stopping = true
                status = "Stopping"
                run = nil
                hev_socks5_server_quit()
                objectWillChange.send()
            }
            return
        }
        if desired == nil || retry || desired != attempted { startDesired() }
    }

    private func startDesired() {
        attempted = desired
        guard let desired else {
            if status != "Stopped" {
                status = "Stopped"
                objectWillChange.send()
            }
            return
        }
        do {
            let configuration = try desired.configuration()
            // The prior native call has returned before this new intent begins.
            hev_socks5_server_prepare()
            let id = UUID()
            current = desired
            currentID = id
            run = Run(id: id, settings: desired)
            isRunning = true
            status = "Running"
            DispatchQueue.global(qos: .utility).async {
                let result = hev_socks5_server_main_from_str(configuration, UInt32(configuration.utf8.count))
                Task { @MainActor in self.finished(result, id: id) }
            }
            // Publish only after the complete state and invocation are committed.
            // A synchronous subscriber may now Stop without an outer setter
            // subsequently resurrecting the old run or "Running" status.
            objectWillChange.send()
        } catch {
            status = error.localizedDescription
            objectWillChange.send()
        }
    }

    private func finished(_ result: Int32, id: UUID) {
        guard currentID == id else { return }
        let restart = stopping && desired != nil
        current = nil
        currentID = nil
        run = nil
        isRunning = false
        stopping = false
        status = desired == nil ? "Stopped" : "Server exited (\(result)). Check settings, then press Start."
        if restart { startDesired() }
        else { objectWillChange.send() }
    }
}
