import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

private final class Trace: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [PeriodicUDPEchoService.State] = []
    func append(_ state: PeriodicUDPEchoService.State) {
        lock.lock()
        values.append(state)
        lock.unlock()
    }
    func snapshot() -> [PeriodicUDPEchoService.State] {
        lock.lock()
        defer { lock.unlock() }
        return values
    }
}

@main
private struct UDPEchoSendStateProbe {
    static func main() async throws {
        let multiple = CommandLine.arguments.count > 2
        let trace = Trace()
        let service = PeriodicUDPEchoService(onState: { trace.append($0) })
        service.setServer(.init(server: .init(host: "127.0.0.1",
                          port: UInt16(CommandLine.arguments[1])!)!), runID: UUID())
        service.update(.init(enabled: true, destinations: multiple ? "127.0.0.1,127.0.0.2" : "127.0.0.1", period: "80"))
        let deadline = DispatchTime.now().uptimeNanoseconds + 3_000_000_000
        while (trace.snapshot().last?.sentCount ?? 0) < (multiple ? 6 : 3) && DispatchTime.now().uptimeNanoseconds < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        service.update(.init(enabled: false))
        service.shutdown()
        try await Task.sleep(for: .milliseconds(100))
        let states = trace.snapshot()
        let rows = states.map { ["text": $0.text, "sentCount": String($0.sentCount)] }
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: rows, options: .sortedKeys) + Data([10]))
        guard states.contains(where: { $0.sentCount >= (multiple ? 6 : 3) }) else {
            FileHandle.standardError.write(Data("SEND_STATE_SETUP_OR_CADENCE_FAILURE\n".utf8))
            exit(75)
        }
        let error = states.firstIndex { $0.text.hasPrefix("UDP send error") && $0.sentCount == 1 }
        let recovered = error.map { index in
            let following = states.dropFirst(index + 1)
            return following.contains { $0.text == "Sending UDP Echo" && $0.sentCount >= (multiple ? 4 : 2) } &&
                !following.contains { $0.text == "Sending UDP Echo" && $0.sentCount < (multiple ? 4 : 2) }
        } ?? false
        guard error != nil && recovered else {
            FileHandle.standardError.write(Data("SEND_STATE_ERROR_THEN_RECOVERY\n".utf8))
            exit(74)
        }
        print("PASS: successful write, repeated drops visible, successful recovery clears error")
    }
}
