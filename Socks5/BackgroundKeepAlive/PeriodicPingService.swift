import Dispatch
import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Numeric addresses only: parsing never performs a DNS request.
struct PingDestination: Sendable {
    let name: String
    let family: Int32
    var address: sockaddr_storage
    let length: socklen_t

    init(_ text: String) throws {
        guard !text.utf8.contains(0) else { throw PingInputError.address }
        var storage = sockaddr_storage()
        var v4 = in_addr()
        var v6 = in6_addr()
        var normalized = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
        if inet_pton(AF_INET, text, &v4) == 1 {
            var value = sockaddr_in()
            #if canImport(Darwin)
            value.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            #endif
            value.sin_family = sa_family_t(AF_INET)
            value.sin_addr = v4
            withUnsafeMutableBytes(of: &storage) { output in
                withUnsafeBytes(of: value) { output.copyMemory(from: $0) }
            }
            inet_ntop(AF_INET, &v4, &normalized, socklen_t(normalized.count))
            family = AF_INET
            length = socklen_t(MemoryLayout<sockaddr_in>.size)
            name = String(cString: normalized)
        } else {
            let parts = text.split(separator: "%", omittingEmptySubsequences: false)
            guard (1...2).contains(parts.count), inet_pton(AF_INET6, String(parts[0]), &v6) == 1 else {
                throw PingInputError.address
            }
            let raw = withUnsafeBytes(of: v6) { Array($0) }
            if raw.prefix(10).allSatisfy({ $0 == 0 }), raw[10] == 255, raw[11] == 255 {
                guard parts.count == 1 else { throw PingInputError.address }
                self = try PingDestination(raw.suffix(4).map(String.init).joined(separator: "."))
                return
            }
            var scope: UInt32 = 0
            if parts.count == 2 {
                guard !parts[1].isEmpty else { throw PingInputError.address }
                scope = UInt32(parts[1]) ?? if_nametoindex(String(parts[1]))
                guard scope != 0 else { throw PingInputError.address }
            }
            var value = sockaddr_in6()
            #if canImport(Darwin)
            value.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            #endif
            value.sin6_family = sa_family_t(AF_INET6)
            value.sin6_addr = v6
            value.sin6_scope_id = scope
            withUnsafeMutableBytes(of: &storage) { output in
                withUnsafeBytes(of: value) { output.copyMemory(from: $0) }
            }
            inet_ntop(AF_INET6, &v6, &normalized, socklen_t(normalized.count))
            family = AF_INET6
            length = socklen_t(MemoryLayout<sockaddr_in6>.size)
            name = String(cString: normalized) + (scope == 0 ? "" : "%\(scope)")
        }
        address = storage
    }
}

enum PingInputError: String, Error, LocalizedError {
    case address = "Enter numeric IPv4 or IPv6 addresses separated by commas."
    case count = "Enter 1 to 64 different destination IPs (at most 8,192 bytes)."
    case period = "Period must be a positive whole number of milliseconds."
    var errorDescription: String? { rawValue }
}

struct PeriodicPingConfiguration: Sendable {
    let destinations: [PingDestination]
    let periodMilliseconds: Int

    init(destinations text: String, period: String) throws {
        guard text.utf8.count <= 8_192 else { throw PingInputError.count }
        let tokens = text.replacingOccurrences(of: "\n", with: ",")
            .split(separator: ",", omittingEmptySubsequences: false)
        var seen = Set<String>()
        var addresses: [PingDestination] = []
        for token in tokens {
            let address = try PingDestination(String(token).trimmingCharacters(in: .whitespacesAndNewlines))
            if seen.insert(address.name).inserted { addresses.append(address) }
            guard addresses.count <= 64 else { throw PingInputError.count }
        }
        guard !addresses.isEmpty else { throw PingInputError.count }
        let digits = period.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !digits.isEmpty, digits.utf8.allSatisfy({ (48...57).contains($0) }),
              let milliseconds = Int(digits), milliseconds > 0,
              milliseconds <= Int.max / 1_000_000 else { throw PingInputError.period }
        destinations = addresses
        periodMilliseconds = milliseconds
    }
}

/// The IPv4 checksum is supplied by us; Darwin computes the ICMPv6 checksum.
enum PingPacket {
    static func echo(ipv6: Bool, identifier: UInt16, sequence: UInt16) -> [UInt8] {
        var bytes: [UInt8] = [ipv6 ? 128 : 8, 0, 0, 0,
                             UInt8(identifier >> 8), UInt8(identifier & 255),
                             UInt8(sequence >> 8), UInt8(sequence & 255)]
        if !ipv6 {
            var sum: UInt32 = 0
            for i in stride(from: 0, to: bytes.count, by: 2) {
                sum += UInt32(bytes[i]) << 8 | UInt32(bytes[i + 1])
            }
            while sum > 0xffff { sum = (sum & 0xffff) + (sum >> 16) }
            let checksum = ~UInt16(sum)
            bytes[2] = UInt8(checksum >> 8)
            bytes[3] = UInt8(checksum & 255)
        }
        return bytes
    }
}

/// Public handle. The worker and every socket/timer mutation stay on one queue.
final class PeriodicPingService: Sendable {
    private let worker = PeriodicPingWorker()

    func configure(_ configuration: PeriodicPingConfiguration?, report: @escaping @Sendable (String) -> Void) {
        let owner = worker
        owner.queue.async { owner.configure(configuration, report: report) }
    }

    deinit {
        let owner = worker
        owner.queue.async { owner.stop() }
    }
}

/// Checked at the public boundary; mutable fields below are exclusively queue-confined.
private final class PeriodicPingWorker: @unchecked Sendable {
    let queue = DispatchQueue(label: "hev.Socks5.periodic-ping", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var configuration: PeriodicPingConfiguration?
    private var sockets: [Int32: Int32] = [:]
    private var report: (@Sendable (String) -> Void)?
    private var lastStatus: String?
    private let identifier = UInt16.random(in: .min ... .max)
    private var sequence: UInt16 = 0
    private var generation = UUID()
    private var receiveBuffer = [UInt8](repeating: 0, count: 256)

    func configure(_ next: PeriodicPingConfiguration?, report: @escaping @Sendable (String) -> Void) {
        stop()
        self.report = report
        configuration = next
        lastStatus = nil
        guard let next else { publish("Off"); return }
        let source = DispatchSource.makeTimerSource(queue: queue)
        timer = source
        let period = next.periodMilliseconds
        source.schedule(deadline: .now(), repeating: .milliseconds(period),
                        leeway: .milliseconds(min(10, period / 20)))
        let generation = self.generation
        source.setEventHandler { [weak self] in
            guard let self, self.generation == generation else { return }
            self.tick()
        }
        source.resume()
    }

    func stop() {
        generation = UUID()
        timer?.setEventHandler {}
        timer?.cancel()
        timer = nil
        configuration = nil
        for socket in sockets.values { close(socket) }
        sockets.removeAll(keepingCapacity: true)
        report = nil
    }

    private func publish(_ status: String) {
        guard lastStatus != status else { return }
        lastStatus = status
        report?(status)
    }

    private func openSocket(_ family: Int32) -> (Int32, Int32) {
        if let socket = sockets[family] { return (socket, 0) }
        #if canImport(Darwin)
        let kind = SOCK_DGRAM
        #else
        let kind = Int32(SOCK_DGRAM.rawValue)
        #endif
        let socket = socket(family, kind, family == AF_INET ? Int32(IPPROTO_ICMP) : Int32(IPPROTO_ICMPV6))
        guard socket >= 0 else { return (-1, errno) }
        let flags = fcntl(socket, F_GETFL, 0)
        guard flags >= 0, fcntl(socket, F_SETFL, flags | O_NONBLOCK) == 0,
              fcntl(socket, F_SETFD, FD_CLOEXEC) == 0 else {
            let error = errno
            close(socket)
            return (-1, error)
        }
        sockets[family] = socket
        return (socket, 0)
    }

    private func tick() {
        guard let configuration else { return }
        // No receive source, RTT history, blocking wait, or task per destination.
        // Discard bounded queued replies; this feature reports sends, not reachability.
        for socket in sockets.values {
            for _ in 0..<64 {
                if recv(socket, &receiveBuffer, receiveBuffer.count, Int32(MSG_DONTWAIT)) < 0 { break }
            }
        }
        let v4 = PingPacket.echo(ipv6: false, identifier: identifier, sequence: sequence)
        let v6 = PingPacket.echo(ipv6: true, identifier: identifier, sequence: sequence)
        sequence &+= 1
        var opened: [Int32: (Int32, Int32)] = [:]
        var failures: [String] = []
        for var destination in configuration.destinations {
            let family = destination.family
            // A failed socket open is retried next period, not once per target.
            if opened[family] == nil { opened[family] = openSocket(family) }
            let (socket, openError) = opened[family]!
            let packet = family == AF_INET ? v4 : v6
            var sent = -1
            var error = openError
            if socket >= 0 {
                sent = packet.withUnsafeBytes { bytes in
                    withUnsafePointer(to: &destination.address) { pointer in
                        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                            sendto(socket, bytes.baseAddress, bytes.count, Int32(MSG_DONTWAIT), $0, destination.length)
                        }
                    }
                }
                error = sent < 0 ? errno : EIO
            }
            if sent != packet.count {
                failures.append("\(destination.name): \(String(cString: strerror(error)))")
            }
        }
        if failures.isEmpty {
            publish("Sending ICMP to \(configuration.destinations.count) destination(s)")
        } else {
            publish("Send error: " + failures.joined(separator: "; "))
        }
    }
}
