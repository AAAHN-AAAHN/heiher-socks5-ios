import Foundation
import HevSocks5Server
var incoming: UInt64 = 9
var outgoing: UInt64 = 9
hev_socks5_server_endpoint_stats(&incoming, &outgoing)
precondition(incoming == 0 && outgoing == 0)
let capacity = hev_socks5_server_endpoint_rows(nil, 0)
precondition(capacity == 1)
var rows = [HevSocks5EndpointStats](repeating: HevSocks5EndpointStats(), count: capacity)
let required = rows.withUnsafeMutableBufferPointer {
    hev_socks5_server_endpoint_rows($0.baseAddress, $0.count)
}
precondition(required == 1 && rows[0].id == 0)
precondition(rows[0].received == 0 && rows[0].sent == 0)
let address = withUnsafePointer(to: &rows[0].address) {
    $0.withMemoryRebound(to: CChar.self, capacity: 64) { String(cString: $0) }
}
precondition(address == "Unattributed")
print("PASS: actual new C ABI imported by Swift; bounded rows and directions. Not a SwiftUI/iOS SDK test.")
