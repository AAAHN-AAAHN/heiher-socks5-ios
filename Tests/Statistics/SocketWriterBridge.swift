import Foundation
import HevSocks5Server

@main
struct SocketWriterBridge {
    static func main() {
        var peer = sockaddr_in()
        #if canImport(Darwin)
        peer.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        #endif
        peer.sin_family = sa_family_t(AF_INET)
        precondition(inet_pton(AF_INET, "192.0.2.44", &peer.sin_addr) == 1)
        var writer: SocketIOWriter? = SocketIOWriter()
        precondition(writer != nil)
        withUnsafePointer(to: &peer) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { address in
                let length = socklen_t(MemoryLayout<sockaddr_in>.size)
                writer!.record(address, length: length, bytes: 0, sent: true)
                writer!.record(address, length: length, bytes: -1, sent: false)
                writer!.record(address, length: length, bytes: 17, sent: true)
                writer!.record(address, length: length, bytes: 23, sent: false)
            }
        }
        writer = nil
        var received: UInt64 = 0
        var sent: UInt64 = 0
        hev_socks5_server_endpoint_stats(&received, &sent)
        precondition(received == 17 && sent == 23)
        // The registry always includes its zero-valued Unattributed row.
        var rows = [HevSocks5EndpointStats](repeating: HevSocks5EndpointStats(), count: 2)
        precondition(rows.withUnsafeMutableBufferPointer {
            hev_socks5_server_endpoint_rows($0.baseAddress, $0.count)
        } == 2)
        var row = rows.first { $0.received == 17 }!
        precondition(row.received == 17 && row.sent == 23)
        let capacity = MemoryLayout.size(ofValue: row.address)
        let address = withUnsafePointer(to: &row.address) {
            $0.withMemoryRebound(to: CChar.self, capacity: capacity) {
                String(cString: $0)
            }
        }
        precondition(address == "192.0.2.44")
        print("PASS: production Swift writer ABI, positive bytes, peer direction and retained totals")
    }
}
