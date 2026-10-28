import Foundation
import Dispatch
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

private final class Probe: @unchecked Sendable {
    let queue = DispatchQueue(label: "udp-echo.transport-test")
    let done = DispatchSemaphore(value: 0)
    let admission = Socks5UDPClient.Admission()
    var client: Socks5UDPClient?
    var events: [String] = []
    var writes = 0
    var reads = 0
    var datagramWrites = 0
    var udpReadBytes = 0
    var attempts = 0
    var accepted = 0
    var dropped = 0
    var pending = false
    var finished = false
    var greetingOffAcknowledged = false
    let mode: String
    let target: Socks5UDPClient.Address
    let configuration: Socks5UDPClient.Configuration
    let generation: UInt64

    init(mode: String, server: String, port: UInt16, target: String) {
        self.mode = mode
        self.target = Socks5UDPClient.Address(host: target, port: 7)!
        let credentials: Socks5UDPClient.Credentials?
        if mode == "auth" || mode == "auth-long" || mode == "reject-auth" || mode == "wrong-auth" {
            credentials = .init(username: mode == "auth-long" ? String(repeating: "u", count: 255) : "test-user",
                                password: mode == "auth-long" ? String(repeating: "p", count: 255) :
                                    (mode == "wrong-auth" ? "wrong-password" : "test-password"))
        } else { credentials = nil }
        configuration = .init(server: .init(host: server, port: port)!, credentials: credentials)
        generation = admission.begin(enabled: true)
    }

    func run() {
        if mode == "off-before-start" { admission.begin(enabled: false) }
        queue.async { [self] in
            client = Socks5UDPClient(queue: queue, admission: admission, generation: generation,
                                     onEvent: { [weak self] in self?.event($0) },
                                     observe: { [weak self] in self?.observed($0, count: $1, sent: $2) })
            client?.start(configuration: configuration, now: DispatchTime.now().uptimeNanoseconds)
            if mode == "setup-timeout" {
                queue.asyncAfter(deadline: .now() + .milliseconds(70)) { [self] in
                    client?.advance(now: UInt64.max)
                }
            }
        }
        queue.asyncAfter(deadline: .now() + .milliseconds(650)) { [self] in finish() }
        guard done.wait(timeout: .now() + 5) == .success else { fatalError("Transport probe stalled") }
        // Cancellation handlers execute on this same queue before the snapshot.
        let result: [String: Any] = queue.sync {
            ["events": events, "writes": writes, "reads": reads,
             "datagramWrites": datagramWrites, "udpReadBytes": udpReadBytes,
             "attempts": attempts, "accepted": accepted, "dropped": dropped,
             "greetingOffAcknowledged": greetingOffAcknowledged]
        }
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }

    private func observed(_ peer: Socks5UDPClient.Address, count: Int, sent: Bool) {
        precondition(count > 0)
        if sent { writes += count } else { reads += count }
        if mode == "off-during-greeting", sent, writes == 3, !greetingOffAcknowledged {
            // Observe the complete greeting, including partial writes. The
            // production callback runs outside Admission's lock. Hold only
            // this test queue until an external Off has actually completed;
            // elapsed time cannot establish ordering with the server reply.
            let acknowledged = DispatchSemaphore(value: 0)
            DispatchQueue.global().async { [admission, queue] in
                dispatchPrecondition(condition: .notOnQueue(queue))
                admission.begin(enabled: false)
                acknowledged.signal()
            }
            precondition(acknowledged.wait(timeout: .now() + 2) == .success,
                         "OFF_GREETING_ACK_TIMEOUT")
            greetingOffAcknowledged = true
        }
        if peer.port != configuration.server.port {
            if sent { datagramWrites += count } else { udpReadBytes += count }
        }
    }

    private func event(_ event: Socks5UDPClient.Event) {
        guard !finished else { return }
        switch event {
        case .ready:
            events.append("ready")
            if mode == "off-before-send" { admission.begin(enabled: false) }
            attempt()
            for index in 1..<5 {
                queue.asyncAfter(deadline: .now() + .milliseconds(index * 60)) { [self] in attempt() }
            }
        case .writable:
            if pending { pending = false; send() }
        case .failed(let message):
            events.append("failed: " + message)
        }
    }

    private func attempt() {
        guard !finished, !pending else { return }
        attempts += 1
        send()
    }

    private func send() {
        guard let client else { return }
        switch client.send(to: target, payload: [0]) {
        case .sent: accepted += 1
        case .blocked: pending = true
        case .dropped: dropped += 1
        case .closed: break
        }
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        admission.begin(enabled: false)
        client?.stop()
        client = nil
        queue.async { [self] in done.signal() }
    }
}

@main
private struct Main {
    static func main() {
        if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "addresses" {
            let v4 = Socks5UDPClient.Address(host: "127.0.0.1", port: 7)!
            let mapped = Socks5UDPClient.Address(host: "::ffff:127.0.0.1", port: 7)!
            precondition(v4 == mapped && v4.host == "127.0.0.1")
            precondition(Set([v4, mapped]).count == 1)
            precondition(Socks5UDPClient.Address(host: "127.0.0.1\u{0}garbage", port: 7) == nil)
            precondition(Socks5UDPClient.Address(host: "fe80::1%1", port: 7) == nil)
            precondition(Socks5UDPClient.Address(host: "fe80::1", port: 7)!.requiresScope)
            precondition(Socks5UDPClient.Address(host: "ff02::1", port: 7)!.requiresScope)
            precondition(!Socks5UDPClient.Address(host: "fd00::1", port: 7)!.requiresScope)
            let scoped = Socks5UDPClient.Address(host: "fe80::1%1", port: 7, allowScope: true)!
            precondition(scoped.scope == 1)
            let composed = Socks5UDPClient.Credentials(username: "\u{e9}", password: "p")
            let decomposed = Socks5UDPClient.Credentials(username: "e\u{301}", password: "p")
            precondition(composed != decomposed)
            print("PASS: numeric addresses, mapped identity, scope and credential byte equality")
            return
        }
        precondition(CommandLine.arguments.count == 5)
        Probe(mode: CommandLine.arguments[1], server: CommandLine.arguments[2],
              port: UInt16(CommandLine.arguments[3])!, target: CommandLine.arguments[4]).run()
    }
}
