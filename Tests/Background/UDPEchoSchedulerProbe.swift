import Foundation

private final class Observed: @unchecked Sendable {
    private let lock = NSLock()
    private var writes = 0
    private var readBytes = 0
    private var states = [String]()
    private var prepared = 0
    private var timestamps = [UInt64]()
    private let controlPort: UInt16
    init(controlPort: UInt16) { self.controlPort = controlPort }
    func io(_ peer: Socks5UDPClient.Address, _ bytes: Int, _ write: Bool) {
        guard peer.port != controlPort else { return }
        lock.lock()
        if write {
            writes += 1
            timestamps.append(DispatchTime.now().uptimeNanoseconds)
        } else {
            readBytes += bytes
        }
        lock.unlock()
    }
    func state(_ value: PeriodicUDPEchoService.State) {
        lock.lock()
        states.append(value.text)
        lock.unlock()
    }
    func prepare() {
        lock.lock()
        prepared += 1
        lock.unlock()
    }
    func snapshot() -> (Int, Int, [String], Int, [UInt64]) {
        lock.lock()
        defer { lock.unlock() }
        return (writes, readBytes, states, prepared, timestamps)
    }
}

@main
struct UDPEchoSchedulerProbe {
    private static func require(_ value: Bool, _ marker: String) {
        guard value else {
            FileHandle.standardError.write(Data(("SCHEDULER_PREDICATE: " + marker + "\n").utf8))
            preconditionFailure(marker)
        }
    }

    static func main() async throws {
        let args = CommandLine.arguments
        let mode = args[1]
        let port = UInt16(args[3])!
        let address = Socks5UDPClient.Address(host: args[2], port: port)!
        let observed = Observed(controlPort: port)
        let service = PeriodicUDPEchoService(prepareObserver: {
            observed.prepare()
            if mode == "statistics-wait" { return nil }
            return { observed.io($0, $1, $2) }
        }, onState: { observed.state($0) })
        defer { service.shutdown() }
        let run = UUID()
        if mode == "resolver-wait" {
            service.setServer(resolve: {
                observed.prepare()
                return nil
            }, runID: run)
        } else {
            let credentials: Socks5UDPClient.Credentials? = mode == "auth" ?
                .init(username: "test-user", password: "test-password") : nil
            service.setServer(.init(server: address, credentials: credentials), runID: run)
        }
        let active = PeriodicUDPEchoSettings(enabled: true, destinations: args[4], period: "20")
        let families = try PeriodicUDPEchoService.parse(active).targets.filter { !$0.isEmpty }.count
        service.update(active)
        try await Task.sleep(for: .milliseconds(360))
        let activeCount = observed.snapshot().0
        if mode == "invalid-input" {
            service.update(.init(enabled: true, destinations: "invalid.example", period: "20"))
        } else {
            service.update(.init(enabled: false, destinations: args[4], period: "20"))
        }
        // The admission gate closes synchronously. Already accepted I/O may
        // finish its accounting callback; after quiescence no new send is legal.
        try await Task.sleep(for: .milliseconds(30))
        let stoppedCount = observed.snapshot().0
        try await Task.sleep(for: .milliseconds(mode.hasSuffix("-wait") ? 1100 : 140))
        let (count, readBytes, states, prepared, timestamps) = observed.snapshot()
        // Write observations before an optimized precondition trap can end the
        // process without a Swift runtime diagnostic on the target platform.
        let result: [String: Any] = ["writes": count, "activeWrites": activeCount,
                                     "readBytes": readBytes, "states": states, "preparations": prepared,
                                     "stoppedWrites": stoppedCount, "families": families,
                                     "timestamps": timestamps]
        let data = try JSONSerialization.data(withJSONObject: result, options: .sortedKeys)
        FileHandle.standardOutput.write(data + Data([10]))
        require(count == stoppedCount, "OFF_STABLE")
        if mode.hasSuffix("-wait") {
            require(count == 0 && prepared == 1, "WAIT_NO_WORK")
            require(states.contains(mode == "statistics-wait" ?
                "Waiting for traffic statistics" : "Waiting for SOCKS5 listener"), "WAIT_STATE")
        } else {
            require(activeCount >= 5 * families && activeCount <= 20 * families, "ACTIVE_COUNT")
            require(states.contains("Sending UDP Echo"), "SENDING_STATE")
            require(prepared == 1, "PREPARE_ONCE")
            if mode == "silence" { require(readBytes == 0, "SILENCE_READS") }
            let intervals = zip(timestamps, timestamps.dropFirst()).map { Double($1 - $0) / 1_000_000 }
            if families == 1 { require(intervals.allSatisfy { $0 >= 8 && $0 < 200 }, "INTERVAL_RANGE") }
        }
    }
}
