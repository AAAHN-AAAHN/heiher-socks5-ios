import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

private final class Metrics: @unchecked Sendable {
    private let lock = NSLock()
    private var writes = 0
    private var reads = 0
    private var states: [String] = []
    func record(_ count: Int, sent: Bool) {
        lock.lock()
        if sent { writes += count } else { reads += count }
        lock.unlock()
    }
    func state(_ state: PeriodicUDPEchoService.State) {
        lock.lock()
        states.append(state.text)
        lock.unlock()
    }
    func snapshot() -> [String: Any] {
        lock.lock()
        defer { lock.unlock() }
        return ["writes": writes, "reads": reads, "states": states]
    }
}

@main
private struct UDPEchoNativeProbe {
    static func main() {
        let args = CommandLine.arguments
        precondition(args.count == 3)
        let credentials: Socks5UDPClient.Credentials? = args[1] == "auth" ?
            .init(username: "test-user", password: "test-password") : nil
        let destinations = args[2]
        let metrics = Metrics()
        let service = PeriodicUDPEchoService(prepareObserver: {
            { _, count, sent in metrics.record(count, sent: sent) }
        }, onState: { metrics.state($0) })
        defer { service.shutdown() }
        service.update(.init(enabled: true, destinations: destinations, period: "20"))
        while let line = readLine() {
            let parts = line.split(separator: " ")
            switch parts.first {
            case "server":
                precondition(parts.count == 3)
                let address = Socks5UDPClient.Address(host: String(parts[1]), port: UInt16(parts[2])!)!
                service.setServer(.init(server: address, credentials: credentials), runID: UUID())
            case "absent":
                service.setServer(nil, runID: nil)
            case "off":
                service.update(.init(enabled: false, destinations: destinations, period: "20"))
            case "on":
                service.update(.init(enabled: true, destinations: destinations, period: "20"))
            case "snapshot":
                break
            default:
                preconditionFailure("Unknown test command")
            }
            let data = try! JSONSerialization.data(withJSONObject: metrics.snapshot(), options: [.sortedKeys])
            print(String(decoding: data, as: UTF8.self))
            fflush(nil)
        }
    }
}
