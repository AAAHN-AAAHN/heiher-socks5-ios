import Foundation
import Dispatch
import HevSocks5Server
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

// Test-only ledgers. The service, client, listener bridge and writer are production code.
private final class PreparedWriter: @unchecked Sendable {
    private let lock = NSLock()
    private var prepared: SocketIOWriter?
    private weak var witness: SocketIOWriter?
    private var calls = 0

    init() {
        let writer = SocketIOWriter()!
        prepared = writer
        witness = writer
    }

    func take() -> SocketIOWriter? {
        lock.lock(); defer { lock.unlock() }
        calls += 1
        let value = prepared
        prepared = nil
        return value
    }

    func snapshot() -> (calls: Int, alive: Bool) {
        lock.lock(); defer { lock.unlock() }
        return (calls, witness != nil)
    }
}

private final class Ledger: @unchecked Sendable {
    private let lock = NSLock()
    private var tcpPort: UInt16 = 0
    private var sent = 0
    private var received = 0
    private var tcpSent = 0
    private var tcpReceived = 0
    private var udpSent = [4: 0, 6: 0]
    private var udpReceived = [4: 0, 6: 0]
    private var peers = Set<String>()
    private var state = ""

    func serverPort(_ port: UInt16) {
        lock.lock(); defer { lock.unlock() }
        tcpPort = port
    }

    func record(_ address: Socks5UDPClient.Address, _ bytes: Int, sent writing: Bool) {
        precondition(bytes > 0 && address.host == "127.0.0.1" && address.port != 0)
        lock.lock(); defer { lock.unlock() }
        peers.insert(address.host + ":" + String(address.port))
        if writing { sent += bytes } else { received += bytes }
        if address.port == tcpPort {
            if writing { tcpSent += bytes } else { tcpReceived += bytes }
        } else {
            // The one-byte Echo payload retains the standard 10/22-byte SOCKS UDP header.
            precondition(bytes == 11 || bytes == 23)
            let family = bytes == 11 ? 4 : 6
            if writing { udpSent[family, default: 0] += 1 }
            else { udpReceived[family, default: 0] += 1 }
        }
    }

    func show(_ value: PeriodicUDPEchoService.State) {
        lock.lock(); defer { lock.unlock() }
        state = value.text
    }

    func settled(_ expected: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return state == expected
    }

    func replies() -> Int {
        lock.lock(); defer { lock.unlock() }
        return udpReceived.values.reduce(0, +)
    }

    func snapshot() -> [String: Any] {
        lock.lock(); defer { lock.unlock() }
        return ["clientSent": sent, "clientReceived": received,
                "tcpSent": tcpSent, "tcpReceived": tcpReceived,
                "udpSent4": udpSent[4]!, "udpSent6": udpSent[6]!,
                "udpReceived4": udpReceived[4]!, "udpReceived6": udpReceived[6]!,
                "peers": peers.sorted(), "state": state]
    }
}

private func waitFor(_ condition: () -> Bool) {
    let deadline = DispatchTime.now().uptimeNanoseconds + 5_000_000_000
    while !condition() {
        precondition(DispatchTime.now().uptimeNanoseconds < deadline, "Combined accounting probe timed out")
        usleep(1000)
    }
}

private func nativeSnapshot() -> [String: Any] {
    var received: UInt64 = 0
    var sent: UInt64 = 0
    hev_socks5_server_endpoint_stats(&received, &sent)
    let count = hev_socks5_server_endpoint_rows(nil, 0)
    var nativeRows = [HevSocks5EndpointStats](repeating: HevSocks5EndpointStats(), count: count)
    precondition(nativeRows.withUnsafeMutableBufferPointer {
        hev_socks5_server_endpoint_rows($0.baseAddress, $0.count)
    } == count)
    let rows: [[String: Any]] = nativeRows.map { value in
        var row = value
        let capacity = MemoryLayout.size(ofValue: row.address)
        let address = withUnsafePointer(to: &row.address) {
            $0.withMemoryRebound(to: CChar.self, capacity: capacity) { String(cString: $0) }
        }
        return ["address": address, "received": row.received, "sent": row.sent]
    }
    return ["generation": hev_socks5_server_endpoint_generation(),
            "received": received, "sent": sent, "rows": rows]
}

@main
private struct PeriodicEchoMeter {
    static func main() {
        // Allocate the real producer before any native engine/TLS initialization.
        let prepared = PreparedWriter()
        let ledger = Ledger()
        var service: PeriodicUDPEchoService? = PeriodicUDPEchoService(prepareObserver: {
            guard let writer = prepared.take() else { return nil }
            return { address, bytes, sent in
                // Same sockaddr/record bridge as the production AppRoot observer.
                address.withSockAddr { writer.record($0, length: $1, bytes: bytes, sent: sent) }
                ledger.record(address, bytes, sent: sent)
            }
        }, onState: { ledger.show($0) })
        let on = PeriodicUDPEchoSettings(enabled: true, destinations: "127.0.0.1,::1", period: "60000")
        let off = PeriodicUDPEchoSettings(enabled: false, destinations: on.destinations, period: on.period)
        var native: DispatchGroup?
        var udpReservation: Int32 = -1
        while let command = readLine() {
            switch command {
            case "start1", "start4":
                precondition(native == nil)
                let oldGeneration = hev_socks5_server_endpoint_generation()
                let workers = command == "start1" ? 1 : 4
                let configuration = """
                main:
                  workers: \(workers)
                  port: 0
                  udp-port: 0
                  listen-address: '127.0.0.1'
                  udp-listen-address: '127.0.0.1'
                  bind-address-v4: '127.0.0.1'
                  bind-address-v6: '::1'
                auth:
                  username: test-user
                  password: test-password
                misc:
                  log-file: null
                """
                hev_socks5_server_prepare()
                let returned = DispatchGroup()
                native = returned
                returned.enter()
                DispatchQueue.global().async {
                    precondition(hev_socks5_server_main_from_str(configuration, UInt32(configuration.utf8.count)) == 0)
                    returned.leave()
                }
                waitFor {
                    hev_socks5_server_endpoint_generation() != oldGeneration &&
                        Socks5ServerEndpoint.resolve() != nil
                }
                let address = Socks5ServerEndpoint.resolve()!
                ledger.serverPort(address.port)
                // Keep TCP/UDP peer ports distinct for the independent test ledger.
                #if canImport(Darwin)
                udpReservation = socket(AF_INET, SOCK_DGRAM, 0)
                #else
                udpReservation = socket(AF_INET, Int32(SOCK_DGRAM.rawValue), 0)
                #endif
                precondition(udpReservation >= 0)
                if address.withSockAddr({ bind(udpReservation, $0, $1) }) < 0 {
                    precondition(errno == EADDRINUSE)
                    close(udpReservation)
                    udpReservation = -1
                }
                service!.setServer(.init(server: address, credentials: .init(
                    username: "test-user", password: "test-password")), runID: UUID())
            case "on":
                let replies = ledger.replies()
                service!.update(on)
                waitFor { ledger.replies() == replies + 2 }
            case "off":
                service!.update(off)
                waitFor { ledger.settled("Off") }
            case "stop":
                service?.setServer(nil, runID: nil)
                hev_socks5_server_quit()
                precondition(native!.wait(timeout: .now() + 5) == .success)
                native = nil
                if udpReservation >= 0 { close(udpReservation); udpReservation = -1 }
            case "release":
                service!.shutdown()
                service = nil
                waitFor { !prepared.snapshot().alive }
            case "snapshot": break
            case "exit":
                precondition(native == nil && service == nil)
            default: preconditionFailure("Unknown accounting probe command")
            }
            let producer = prepared.snapshot()
            let result: [String: Any] = ["client": ledger.snapshot(), "native": nativeSnapshot(),
                                         "factoryCalls": producer.calls, "writerAlive": producer.alive]
            let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
            FileHandle.standardOutput.write(data + Data([10]))
            if command == "exit" { return }
        }
        preconditionFailure("Probe command transport ended before cleanup")
    }
}
