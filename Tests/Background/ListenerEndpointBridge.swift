import Foundation
import Dispatch
import HevSocks5Server

@main
struct ListenerEndpointBridge {
    static func main() {
        let cases = [
            ("127.0.0.1", false, false, "127.0.0.1"),
            ("0.0.0.0", false, false, "127.0.0.1"),
            ("::", false, false, "::1"),
            ("::", false, true, "127.0.0.1"),
            ("::", true, true, "::1"),
            ("::1", true, true, "::1")
        ]
        for (host, ipv6Only, preferIPv4, expected) in cases {
            precondition(Socks5ServerEndpoint.resolve(preferIPv4: preferIPv4) == nil)
            let configuration = """
            main:
              workers: 1
              port: 0
              udp-port: 0
              listen-address: '\(host)'
              listen-ipv6-only: \(ipv6Only)
            """
            let returned = DispatchGroup()
            hev_socks5_server_prepare()
            returned.enter()
            DispatchQueue.global().async {
                let result = hev_socks5_server_main_from_str(configuration, UInt32(configuration.utf8.count))
                precondition(result == 0)
                returned.leave()
            }
            var address: Socks5UDPClient.Address?
            for _ in 0..<5000 {
                address = Socks5ServerEndpoint.resolve(preferIPv4: preferIPv4)
                if address != nil { break }
                usleep(1000)
            }
            precondition(address?.host == expected && address!.port != 0)
            hev_socks5_server_quit()
            precondition(Socks5ServerEndpoint.resolve(preferIPv4: preferIPv4) == nil)
            precondition(returned.wait(timeout: .now() + 5) == .success)
        }
        print("PASS: actual native listener Swift ABI, mapped IPv4, wildcard/dual-stack choices and Stop invalidation")
    }
}
