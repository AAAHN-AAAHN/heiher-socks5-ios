import Foundation
import HevSocks5Server

/// Discovers one real listener. All client traffic still uses ordinary SOCKS5.
enum Socks5ServerEndpoint {
    static func resolve(preferIPv4: Bool = false) -> Socks5UDPClient.Address? {
        var info = HevSocks5ListenerInfo()
        guard hev_socks5_server_listener_info(&info) == 1 else { return nil }
        var host = withUnsafePointer(to: &info.address) {
            $0.withMemoryRebound(to: CChar.self, capacity: 64) { String(cString: $0) }
        }
        if host == "0.0.0.0" || host == "::ffff:0.0.0.0" {
            host = "127.0.0.1"
        } else if host == "::" {
            host = preferIPv4 && info.ipv6_only == 0 ? "127.0.0.1" : "::1"
        }
        return Socks5UDPClient.Address(host: host, port: info.port, allowScope: true)
    }
}
