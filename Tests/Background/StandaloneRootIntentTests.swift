import Foundation
#if canImport(Combine)
import Combine
#endif

private final class RootEndpoint: LoopAudioEndpoint, Sendable {
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        switch command {
        case .stop: completion(.init())
        case .start, .inspect:
            guard context.mayStart() else { completion(.init(superseded: true)); return }
            let now = ProcessInfo.processInfo.systemUptime
            completion(.init(sample: .init(generation: 1, epoch: context.epoch,
                playing: true, configured: true, position: now.truncatingRemainder(dividingBy: 0.05),
                deviceTime: now, duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001)))
        }
    }
}
extension LoopAudioService {
    @MainActor static let shared = LoopAudioService { _, _ in RootEndpoint() }
}

@MainActor final class RootBindingFixture {
    let keepAlive: BackgroundKeepAlive
    var audioEnabled = false
    init(_ service: LoopAudioService) { keepAlive = BackgroundKeepAlive(audioService: service) }
    func set(_ value: Bool) {
        // ACTUAL_ROOT_SETTER
    }
    func echo() { keepAlive.syncAudio(audioEnabled) }
}

@main struct StandaloneRootIntentTests {
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 2 else { exit(2) }
        let name = CommandLine.arguments[1]
        guard ["nested-off", "nested-on", "plain-toggle", "publication-off"].contains(name) else { exit(2) }
        let service = LoopAudioService { _, _ in RootEndpoint() }
        let root = RootBindingFixture(service)
        let latest = name == "nested-on"
        if latest { root.set(true) }
        var once = false
        var failures = [String]()
        if name == "plain-toggle" {
            root.set(true)
            root.echo()
            if !root.audioEnabled || !root.keepAlive.audioEnabled { failures.append("ORDINARY_ON_NOT_PERSISTED") }
            root.set(false)
            once = true
        } else {
            let subscription = root.keepAlive.objectWillChange.sink { _ in
                let boundary = name == "publication-off" ?
                    root.keepAlive.audioState == LoopAudioService.Phase.playing.rawValue :
                    root.keepAlive.audioEnabled == !latest
                if !once && boundary {
                    once = true
                    root.set(latest)
                }
            }
            root.set(!latest)
            if name == "publication-off" {
                let deadline = ProcessInfo.processInfo.systemUptime + 3
                while !once && ProcessInfo.processInfo.systemUptime < deadline {
                    try? await Task.sleep(nanoseconds: 1_000_000)
                }
            }
            subscription.cancel()
        }
        let beforeEcho = root.keepAlive.audioEnabled
        let stored = root.audioEnabled
        root.echo()
        let afterEcho = root.keepAlive.audioEnabled
        if !once || beforeEcho != latest { failures.append("FIXTURE_NEWER_INTENT_NOT_ACCEPTED") }
        if stored != latest || afterEcho != latest { failures.append("STANDALONE_STORAGE_ECHO_OVERWROTE_LATEST_INTENT") }
        root.set(false)
        root.echo()
        let limit = ProcessInfo.processInfo.systemUptime + 3
        var cleanup = false
        while ProcessInfo.processInfo.systemUptime < limit {
            let diag: LoopAudioService.Diagnostics = await withCheckedContinuation { continuation in
                service.diagnostics { continuation.resume(returning: $0) }
            }
            if diag.operation == nil && !diag.timerActive && diag.maximumOutstanding <= 1 &&
               !root.keepAlive.audioEnabled && root.keepAlive.audioState == "Off" {
                cleanup = true; break
            }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        if !cleanup { failures.append("FINAL_OFF_CLEANUP_FAILED") }
        #if canImport(Combine)
        let publication = "actual Combine"
        #else
        let publication = "explicit synchronous publisher double"
        #endif
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL", "failures": failures,
            "cleanup_passed": cleanup, "latest_intent": latest, "intent_before_echo": beforeEcho,
            "stored_value": stored, "intent_after_echo": afterEcho,
            "scope": "Actual standalone binding setter and facade/service; \(publication) and storage-value double; no SwiftUI/device execution"]
        print(String(decoding: try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
