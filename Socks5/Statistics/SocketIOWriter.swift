import Foundation
import HevSocks5Server

/// One explicit writer for a serial socket queue, independent of its OS thread.
/// An observer retains this object until every queued I/O callback has ended.
final class SocketIOWriter: @unchecked Sendable {
    private let handle: UnsafeMutableRawPointer

    init?() {
        guard let handle = hev_socks5_server_io_writer_new() else { return nil }
        self.handle = handle
    }

    /// Call only from the owning serial queue; use the actual socket peer.
    func record(_ address: UnsafePointer<sockaddr>, length: socklen_t,
                bytes: Int, sent: Bool) {
        guard bytes > 0 else { return }
        hev_socks5_server_io_writer_record(handle, address, length,
                                           sent ? numericCast(bytes) : 0,
                                           sent ? 0 : numericCast(bytes))
    }

    deinit { hev_socks5_server_io_writer_free(handle) }
}
