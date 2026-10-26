import Dispatch
import Foundation
import HevSocks5Server
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

private final class NativeEchoResults: @unchecked Sendable {
    private let lock = NSLock()
    private var replies: [UInt64: [UInt8]] = [:]
    private var errors: [UInt64: Int32] = [:]
    private var status = ""
    func receive(_ result: HevSocks5IcmpResult) {
        lock.lock(); defer { lock.unlock() }
        if result.event == HEV_SOCKS5_ICMP_REPLY, let bytes = result.echo {
            replies[result.request_id] = Array(UnsafeBufferPointer(start: bytes, count: Int(result.echo_len)))
        } else if result.event == HEV_SOCKS5_ICMP_ERROR {
            errors[result.request_id] = result.error
        }
    }
    func report(_ value: String) { lock.lock(); status = value; lock.unlock() }
    var state: String { lock.lock(); defer { lock.unlock() }; return status }
    func result(_ id: UInt64) -> ([UInt8]?, Int32?) {
        lock.lock(); defer { lock.unlock() }
        return (replies[id], errors[id])
    }
}

private func echoResult(_ result: UnsafePointer<HevSocks5IcmpResult>?, _ context: UnsafeMutableRawPointer?) {
    guard let result, let context else { return }
    Unmanaged<NativeEchoResults>.fromOpaque(context).takeUnretainedValue().receive(result.pointee)
}

/// Real Background/native API and native ICMP loopback; never links the mock.
@main
struct PeriodicPingLoopback {
    static func wait(_ label: String, _ predicate: () -> Bool) {
        let deadline = Date().addingTimeInterval(5)
        while !predicate(), Date() < deadline { Thread.sleep(forTimeInterval: 0.002) }
        precondition(predicate(), label)
    }

    static func check() throws -> Int32 {
        let finished = DispatchSemaphore(value: 0)
        let configuration = """
        main:
          workers: 1
          listen-address: '127.0.0.1'
          port: 0
          udp-port: 0
        """
        Thread.detachNewThread {
            let result = configuration.withCString {
                hev_socks5_server_main_from_str(UnsafeRawPointer($0).assumingMemoryBound(to: UInt8.self),
                                                UInt32(configuration.utf8.count))
            }
            precondition(result == 0, "native server failed")
            finished.signal()
        }
        defer {
            hev_socks5_server_quit()
            precondition(finished.wait(timeout: .now() + 5) == .success, "native server did not stop")
        }
        wait("native ICMP server never became ready") { hev_socks5_server_icmp_generation() != 0 }
        let results = NativeEchoResults()
        let context = Unmanaged.passRetained(results).toOpaque()
        guard let client = hev_socks5_server_icmp_client_new(hev_socks5_server_icmp_generation(), echoResult, context) else {
            Unmanaged<NativeEchoResults>.fromOpaque(context).release()
            preconditionFailure("native ICMP client: \(errno)")
        }
        defer {
            hev_socks5_server_icmp_client_free(client)
            Unmanaged<NativeEchoResults>.fromOpaque(context).release()
        }
        for (index, text) in ["127.0.0.1", "::1"].enumerated() {
            var target = try PingDestination(text)
            let id = UInt64(index + 1)
            let status = withUnsafePointer(to: &target.address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    hev_socks5_server_icmp_ping(client, id, $0, target.length, 2000)
                }
            }
            precondition(status == 0, "native ping submission failed: \(status)")
            wait("native loopback did not complete") {
                let value = results.result(id)
                return value.0 != nil || value.1 != nil
            }
            let (reply, error) = results.result(id)
            if let error {
                #if os(Linux)
                if error == EACCES || error == EPERM {
                    print("SKIP: host denies native unprivileged ICMP; no loopback success claimed")
                    return 77
                }
                #endif
                preconditionFailure("native ICMP loopback: \(error)")
            }
            precondition(reply?.count == 8 && reply?[0] == (index == 0 ? 0 : 129) && reply?[1] == 0,
                         "native reply is not the corresponding Echo message")
            print("PASS: native ICMP Echo Reply from \(text)")
        }
        var service: PeriodicPingService? = PeriodicPingService()
        service!.configure(try PeriodicPingConfiguration(destinations: "127.0.0.1,::1", period: "20")) {
            results.report($0)
        }
        wait("Background did not consume native SENT events") { results.state == "Sending ICMP to 2 destination(s)" }
        service!.configure(nil) { results.report($0) }
        wait("Background native client did not stop") { results.state == "Off" }
        service = nil
        print("PASS: actual Background service/native client/worker loopback and Off")
        return 0
    }

    static func main() throws { exit(try check()) }
}
