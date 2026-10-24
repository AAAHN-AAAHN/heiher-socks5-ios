import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Real, unprivileged ICMP loopback smoke; never uses the syscall double.
@main
struct PeriodicPingLoopback {
    static func main() throws {
        for text in ["127.0.0.1", "::1"] {
            var target = try PingDestination(text)
            #if canImport(Darwin)
            let kind = SOCK_DGRAM
            #else
            let kind = Int32(SOCK_DGRAM.rawValue)
            #endif
            let fd = socket(target.family, kind, target.family == AF_INET ? Int32(IPPROTO_ICMP) : Int32(IPPROTO_ICMPV6))
            if fd < 0 {
                if errno == EACCES || errno == EPERM {
                    print("SKIP: host denies unprivileged ICMP sockets; no echo success claimed")
                    exit(77)
                }
                fatalError("ICMP socket: \(errno)")
            }
            defer { close(fd) }
            var timeout = timeval(tv_sec: 2, tv_usec: 0)
            precondition(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size)) == 0)
            let sequence: UInt16 = 0x5127
            let packet = PingPacket.echo(ipv6: target.family == AF_INET6, identifier: 0x3462, sequence: sequence)
            let sent = packet.withUnsafeBytes { bytes in
                withUnsafePointer(to: &target.address) { pointer in
                    pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        sendto(fd, bytes.baseAddress, bytes.count, 0, $0, target.length)
                    }
                }
            }
            precondition(sent == packet.count, "Loopback send failed")
            var buffer = [UInt8](repeating: 0, count: 512)
            var matched = false
            for _ in 0..<16 {
                let count = recv(fd, &buffer, buffer.count, 0)
                precondition(count >= 8, "Loopback echo timed out or was truncated")
                let offset = target.family == AF_INET && buffer[0] >> 4 == 4 ? Int(buffer[0] & 15) * 4 : 0
                guard count >= offset + 8 else { continue }
                let type: UInt8 = target.family == AF_INET ? 0 : 129
                if buffer[offset] == type, buffer[offset + 1] == 0,
                   buffer[offset + 6] == UInt8(sequence >> 8), buffer[offset + 7] == UInt8(sequence & 255) {
                    matched = true
                    break
                }
            }
            precondition(matched, "No matching ICMP Echo Reply")
            print("PASS: real ICMP echo reply from \(text)")
        }
    }
}
