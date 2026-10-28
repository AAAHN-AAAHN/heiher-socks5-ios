import Foundation
import Dispatch
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// One UDP association. All methods and callbacks run on the injected serial
/// queue; only Admission is also entered by the user-intent thread.
final class Socks5UDPClient: @unchecked Sendable {
    struct Address: Sendable, Hashable {
        let bytes: [UInt8]
        let port: UInt16
        let scope: UInt32
        var family: Int32 { bytes.count == 4 ? AF_INET : AF_INET6 }
        var isUnspecified: Bool { bytes.allSatisfy { $0 == 0 } }
        var isLinkLocal: Bool {
            bytes.count == 16 && bytes[0] == 0xfe && bytes[1] & 0xc0 == 0x80
        }
        var requiresScope: Bool {
            isLinkLocal || (bytes.count == 16 && bytes[0] == 0xff && bytes[1] & 15 != 14)
        }
        var host: String {
            var text = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
            let converted = bytes.withUnsafeBytes { source in
                text.withUnsafeMutableBufferPointer {
                    inet_ntop(family, source.baseAddress, $0.baseAddress!, socklen_t($0.count)) != nil
                }
            }
            guard converted else { return "" }
            let numeric = text.withUnsafeBufferPointer { String(cString: $0.baseAddress!) }
            return scope == 0 ? numeric : numeric + "%" + String(scope)
        }

        init?(host: String, port: UInt16, allowScope: Bool = false) {
            guard !host.utf8.contains(0) else { return nil }
            let parts = host.split(separator: "%", omittingEmptySubsequences: false)
            guard parts.count == 1 || (allowScope && parts.count == 2 && !parts[1].isEmpty) else {
                return nil
            }
            let numeric = String(parts[0])
            var v4 = in_addr()
            if numeric.withCString({ inet_pton(AF_INET, $0, &v4) }) == 1 {
                guard parts.count == 1 else { return nil }
                self.init(bytes: withUnsafeBytes(of: v4) { Array($0) }, port: port)
                return
            }
            var v6 = in6_addr()
            guard numeric.withCString({ inet_pton(AF_INET6, $0, &v6) }) == 1 else { return nil }
            var zone: UInt32 = 0
            if parts.count == 2 {
                zone = UInt32(parts[1]) ?? String(parts[1]).withCString { if_nametoindex($0) }
                guard zone != 0 else { return nil }
            }
            self.init(bytes: withUnsafeBytes(of: v6) { Array($0) }, port: port, scope: zone)
        }

        fileprivate init(bytes: [UInt8], port: UInt16, scope: UInt32 = 0) {
            // A mapped address has the same network identity as its IPv4 form.
            if bytes.count == 16 && bytes.prefix(10).allSatisfy({ $0 == 0 }) &&
                bytes[10] == 0xff && bytes[11] == 0xff {
                self.bytes = Array(bytes.suffix(4))
                self.scope = 0
            } else {
                self.bytes = bytes
                self.scope = scope
            }
            self.port = port
        }

        func withSockAddr<Result>(_ body: (UnsafePointer<sockaddr>, socklen_t) -> Result) -> Result {
            if family == AF_INET {
                var address = sockaddr_in()
                #if canImport(Darwin)
                address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
                #endif
                address.sin_family = sa_family_t(AF_INET)
                address.sin_port = port.bigEndian
                withUnsafeMutableBytes(of: &address.sin_addr) { $0.copyBytes(from: bytes) }
                return withUnsafePointer(to: &address) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        body($0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
            var address = sockaddr_in6()
            #if canImport(Darwin)
            address.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            #endif
            address.sin6_family = sa_family_t(AF_INET6)
            address.sin6_port = port.bigEndian
            address.sin6_scope_id = scope
            withUnsafeMutableBytes(of: &address.sin6_addr) { $0.copyBytes(from: bytes) }
            return withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    body($0, socklen_t(MemoryLayout<sockaddr_in6>.size))
                }
            }
        }

        fileprivate init?(_ raw: UnsafePointer<sockaddr>, length: socklen_t) {
            if raw.pointee.sa_family == sa_family_t(AF_INET) {
                guard Int(length) >= MemoryLayout<sockaddr_in>.size else { return nil }
                let value = raw.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee }
                self.init(bytes: withUnsafeBytes(of: value.sin_addr) { Array($0) },
                          port: UInt16(bigEndian: value.sin_port))
            } else if raw.pointee.sa_family == sa_family_t(AF_INET6) {
                guard Int(length) >= MemoryLayout<sockaddr_in6>.size else { return nil }
                let value = raw.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) { $0.pointee }
                self.init(bytes: withUnsafeBytes(of: value.sin6_addr) { Array($0) },
                          port: UInt16(bigEndian: value.sin6_port), scope: value.sin6_scope_id)
            } else {
                return nil
            }
        }

        fileprivate func withPort(_ port: UInt16) -> Address {
            Address(bytes: bytes, port: port, scope: scope)
        }
    }

    struct Credentials: Sendable, Equatable {
        let username: String
        let password: String
        static func == (lhs: Self, rhs: Self) -> Bool {
            lhs.username.utf8.elementsEqual(rhs.username.utf8) &&
                lhs.password.utf8.elementsEqual(rhs.password.utf8)
        }
    }
    struct Configuration: Sendable, Equatable {
        let server: Address
        var credentials: Credentials? = nil
    }

    /// The lock covers admission and a single nonblocking syscall, never a
    /// callback or queue wait. begin(false) synchronously closes that boundary.
    final class Admission: @unchecked Sendable {
        private let lock = NSLock()
        private var generation: UInt64 = 0
        private var enabled = false
        @discardableResult func begin(enabled: Bool) -> UInt64 {
            lock.lock()
            defer { lock.unlock() }
            generation &+= 1
            self.enabled = enabled
            return generation
        }
        func isCurrent(_ generation: UInt64) -> Bool {
            lock.lock()
            defer { lock.unlock() }
            return self.generation == generation
        }
        func permits(_ generation: UInt64) -> Bool {
            lock.lock()
            defer { lock.unlock() }
            return enabled && self.generation == generation
        }
        fileprivate func perform<Result>(_ generation: UInt64, _ body: () -> Result) -> Result? {
            lock.lock()
            defer { lock.unlock() }
            guard enabled && self.generation == generation else { return nil }
            return body()
        }
    }

    enum Event: Sendable { case ready, writable, failed(String) }
    enum SendResult: Sendable, Equatable { case sent, blocked, dropped(Int32), closed }
    typealias IOObserver = @Sendable (Address, Int, Bool) -> Void

    private enum Phase {
        case idle, connecting, greeting, authentication, association, resolving, relayConnecting, ready, closed
    }
    private let queue: DispatchQueue
    private let admission: Admission
    private let generation: UInt64
    private let onEvent: @Sendable (Event) -> Void
    private let observe: IOObserver
    private var phase = Phase.idle
    private var configuration: Configuration?
    private var tcp: Channel?
    private var udp: Channel?
    private var tcpPeer: Address?
    private var udpPeer: Address?
    private var udpSource: Address?
    private var input: [UInt8] = []
    private var output: [UInt8] = []
    private var outputOffset = 0
    private var packet = [UInt8](repeating: 0, count: 23)
    private var receiveBuffer = [UInt8](repeating: 0, count: 65_535)
    private var receiveContinuation = false
    private(set) var setupDeadline: UInt64?
    var isReady: Bool { phase == .ready }

    init(queue: DispatchQueue, admission: Admission, generation: UInt64,
         onEvent: @escaping @Sendable (Event) -> Void,
         observe: @escaping IOObserver = { _, _, _ in }) {
        self.queue = queue
        self.admission = admission
        self.generation = generation
        self.onEvent = onEvent
        self.observe = observe
        input.reserveCapacity(262)
    }

    deinit {
        let channels = [tcp, udp]
        queue.async { channels.forEach { $0?.close() } }
    }

    func start(configuration: Configuration, now: UInt64) {
        dispatchPrecondition(condition: .onQueue(queue))
        guard phase == .idle, admission.permits(generation) else { return }
        guard configuration.server.port != 0, !configuration.server.isUnspecified else {
            fail("Invalid SOCKS5 server endpoint.")
            return
        }
        if let credentials = configuration.credentials {
            guard (1...255).contains(credentials.username.utf8.count),
                  (1...255).contains(credentials.password.utf8.count) else {
                fail("SOCKS5 credentials require 1-255 UTF-8 bytes per field.")
                return
            }
        }
        self.configuration = configuration
        let (deadline, overflow) = now.addingReportingOverflow(5_000_000_000)
        setupDeadline = overflow ? UInt64.max : deadline
        let fd = Self.makeSocket(family: configuration.server.family, stream: true)
        guard fd >= 0 else { fail(Self.socketError("Create TCP socket", errno)); return }
        tcp = Channel(fd: fd, queue: queue)
        phase = .connecting
        let result = admission.perform(generation) {
            configuration.server.withSockAddr { address, length -> (Int32, Int32) in
                let value = connect(fd, address, length)
                return (value, errno)
            }
        }
        guard let (value, error) = result else { stop(); return }
        if value == 0 {
            finishConnect()
        } else if error == EINPROGRESS || error == EALREADY || error == EINTR || Self.wouldBlock(error) {
            tcp?.watchWrite { [weak self] in self?.finishConnect() }
        } else {
            fail(Self.socketError("Connect SOCKS5 server", error))
        }
    }

    func advance(now: UInt64) {
        dispatchPrecondition(condition: .onQueue(queue))
        if let deadline = setupDeadline, now >= deadline {
            fail("SOCKS5 connection setup timed out.")
        }
    }

    func stop() {
        dispatchPrecondition(condition: .onQueue(queue))
        phase = .closed
        setupDeadline = nil
        tcp?.close()
        udp?.close()
        tcp = nil
        udp = nil
        configuration = nil
        input.removeAll(keepingCapacity: false)
        output.removeAll(keepingCapacity: false)
    }

    func send(to destination: Address, payload: [UInt8]) -> SendResult {
        dispatchPrecondition(condition: .onQueue(queue))
        guard phase == .ready, let channel = udp, let peer = udpPeer else { return .closed }
        let header = destination.family == AF_INET ? 10 : 22
        guard destination.scope == 0 else { return .dropped(EINVAL) }
        guard payload.count <= 65_507 - header else { return .dropped(EMSGSIZE) }
        let count = header + payload.count
        if packet.count < count { packet.append(contentsOf: repeatElement(0, count: count - packet.count)) }
        packet[0] = 0
        packet[1] = 0
        packet[2] = 0
        packet[3] = destination.family == AF_INET ? 1 : 4
        packet.replaceSubrange(4..<(header - 2), with: destination.bytes)
        packet[header - 2] = UInt8(destination.port >> 8)
        packet[header - 1] = UInt8(destination.port & 255)
        packet.replaceSubrange(header..<count, with: payload)
        for _ in 0..<4 {
            let result = admission.perform(generation) {
                packet.withUnsafeBytes { bytes -> (Int, Int32) in
                    let written = Self.writeSocket(channel.fd, bytes.baseAddress!, count)
                    return (written, errno)
                }
            }
            guard let (written, error) = result else { stop(); return .closed }
            if written >= 0 {
                if written > 0 { observe(peer, written, true) }
                return written == count ? .sent : .dropped(EIO)
            }
            if error == EINTR { continue }
            if Self.wouldBlock(error) { return waitForUDPWrite() }
            if error == EBADF || error == ENOTSOCK || error == ENOTCONN {
                fail(Self.socketError("Send SOCKS5 UDP", error))
                return .closed
            }
            return .dropped(error)
        }
        return waitForUDPWrite()
    }

    private func finishConnect() {
        guard phase == .connecting, let channel = tcp else { return }
        guard admission.permits(generation) else { stop(); return }
        var error: Int32 = 0
        var length = socklen_t(MemoryLayout<Int32>.size)
        guard getsockopt(channel.fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 else {
            fail(Self.socketError("Inspect TCP connection", errno)); return
        }
        guard error == 0 else { fail(Self.socketError("Connect SOCKS5 server", error)); return }
        guard let peer = Self.address(channel.fd, peer: true),
              let local = Self.address(channel.fd, peer: false) else {
            fail(Self.socketError("Read TCP endpoints", errno)); return
        }
        tcpPeer = peer
        let fd = Self.makeSocket(family: local.family, stream: false)
        guard fd >= 0 else { fail(Self.socketError("Create UDP socket", errno)); return }
        let bound = local.withPort(0).withSockAddr { bind(fd, $0, $1) }
        guard bound == 0, let source = Self.address(fd, peer: false), source.port != 0 else {
            let error = errno
            Self.closeSocket(fd)
            fail(Self.socketError("Bind UDP source", error))
            return
        }
        udp = Channel(fd: fd, queue: queue)
        udpSource = source
        queueOutput([5, 1, configuration?.credentials == nil ? 0 : 2], phase: .greeting)
    }

    private func queueOutput(_ bytes: [UInt8], phase: Phase) {
        tcp?.unwatchRead()
        self.phase = phase
        input.removeAll(keepingCapacity: true)
        output = bytes
        outputOffset = 0
        writeTCP()
    }

    private func writeTCP() {
        guard let channel = tcp, let peer = tcpPeer, phase != .closed else { return }
        for _ in 0..<16 where outputOffset < output.count {
            let result = admission.perform(generation) {
                output.withUnsafeBytes { bytes -> (Int, Int32) in
                    let written = Self.writeSocket(channel.fd, bytes.baseAddress!.advanced(by: outputOffset),
                                                   bytes.count - outputOffset)
                    return (written, errno)
                }
            }
            guard let (written, error) = result else { stop(); return }
            if written > 0 {
                outputOffset += written
                observe(peer, written, true)
                continue
            }
            if written < 0 && error == EINTR { continue }
            if written < 0 && Self.wouldBlock(error) { break }
            fail(Self.socketError("Write SOCKS5 control", written == 0 ? EPIPE : error))
            return
        }
        if outputOffset < output.count {
            channel.watchWrite { [weak self] in self?.writeTCP() }
        } else {
            output.removeAll(keepingCapacity: true)
            outputOffset = 0
            channel.unwatchWrite()
            channel.watchRead { [weak self] in self?.readTCP() }
        }
    }

    private func readTCP() {
        guard let channel = tcp, let peer = tcpPeer, output.isEmpty, phase != .closed else { return }
        guard admission.permits(generation) else { stop(); return }
        for _ in 0..<16 {
            let needed: Int
            switch phase {
            case .greeting, .authentication: needed = 2
            case .association:
                if input.count < 4 { needed = 4 }
                else if input[3] == 1 { needed = 10 }
                else if input[3] == 4 { needed = 22 }
                else if input[3] == 3 {
                    if input.count < 5 { needed = 5 }
                    else if input[4] > 0 { needed = 7 + Int(input[4]) }
                    else { fail("Invalid SOCKS5 relay hostname length."); return }
                } else { fail("Unsupported SOCKS5 relay address type."); return }
            case .ready, .resolving, .relayConnecting: needed = 1
            default: return
            }
            let amount = max(1, needed - input.count)
            let consumed = receiveBuffer.withUnsafeMutableBytes {
                recv(channel.fd, $0.baseAddress!, amount, 0)
            }
            if consumed > 0 {
                observe(peer, consumed, false)
                if phase == .ready || phase == .resolving || phase == .relayConnecting {
                    fail("Unexpected data on SOCKS5 UDP control connection.")
                    return
                }
                input.append(contentsOf: receiveBuffer.prefix(consumed))
                if input.count == needed {
                    switch phase {
                    case .greeting:
                        guard input[0] == 5,
                              input[1] == (configuration?.credentials == nil ? 0 : 2) else {
                            fail("SOCKS5 authentication method was rejected."); return
                        }
                        if let credentials = configuration?.credentials {
                            let username = Array(credentials.username.utf8)
                            let password = Array(credentials.password.utf8)
                            queueOutput([1, UInt8(username.count)] + username +
                                        [UInt8(password.count)] + password, phase: .authentication)
                        } else { requestAssociation() }
                        return
                    case .authentication:
                        guard input == [1, 0] else { fail("SOCKS5 authentication failed."); return }
                        requestAssociation()
                        return
                    case .association:
                        if input.count == 4 {
                            guard input[0] == 5, input[1] == 0, input[2] == 0 else {
                                fail("SOCKS5 UDP ASSOCIATE was rejected."); return
                            }
                        } else if input[3] != 3 || input.count > 5 {
                            acceptRelay()
                            return
                        }
                    default: return
                    }
                }
                continue
            }
            if consumed == 0 { fail("SOCKS5 control connection closed."); return }
            let error = errno
            if error == EINTR { continue }
            if Self.wouldBlock(error) { return }
            fail(Self.socketError("Read SOCKS5 control", error))
            return
        }
        // At most 262 reply bytes; continue explicitly after repeated short reads.
        queue.async { [weak self] in self?.readTCP() }
    }

    private func requestAssociation() {
        guard let source = udpSource else { fail("UDP source is unavailable."); return }
        queueOutput([5, 3, 0, source.family == AF_INET ? 1 : 4] + source.bytes +
                    [UInt8(source.port >> 8), UInt8(source.port & 255)], phase: .association)
    }

    private func acceptRelay() {
        let port = (UInt16(input[input.count - 2]) << 8) | UInt16(input[input.count - 1])
        guard port != 0 else { fail("SOCKS5 relay returned port zero."); return }
        if input[3] == 3 {
            let nameBytes = input[5..<(input.count - 2)]
            guard !nameBytes.contains(0), let name = String(bytes: nameBytes, encoding: .utf8),
                  let source = udpSource else {
                fail("Invalid SOCKS5 relay hostname."); return
            }
            phase = .resolving
            RelayResolver.shared.resolve(name, port: port, family: source.family, queue: queue) {
                [weak self] address in
                guard let self, self.phase == .resolving else { return }
                guard self.admission.permits(self.generation) else { self.stop(); return }
                guard let address else { self.fail("SOCKS5 relay hostname could not be resolved."); return }
                self.connectRelay(address)
            }
        } else {
            connectRelay(Address(bytes: Array(input[4..<(input.count - 2)]), port: port))
        }
    }

    private func connectRelay(_ announced: Address) {
        guard let channel = udp, let source = udpSource, let server = tcpPeer else { return }
        // An unspecified BND address identifies no remote interface. Use the
        // established TCP peer, preserving this client's actual source family.
        var relay = announced.isUnspecified ? server.withPort(announced.port) : announced
        let routeScope = source.scope != 0 ? source.scope : server.scope
        if relay.requiresScope && relay.scope == 0 && routeScope != 0 {
            // This is the client's actual TCP route zone, never a zone number
            // interpreted as belonging to the remote server.
            relay = Address(bytes: relay.bytes, port: relay.port, scope: routeScope)
        }
        guard relay.family == source.family,
              !relay.requiresScope || relay.scope != 0 else {
            fail("SOCKS5 relay is incompatible with the UDP source address."); return
        }
        phase = .relayConnecting
        let result = admission.perform(generation) {
            relay.withSockAddr { address, length -> (Int32, Int32) in
                let value = connect(channel.fd, address, length)
                return (value, errno)
            }
        }
        guard let (value, error) = result else { stop(); return }
        if value == 0 {
            finishRelayConnect()
        } else if error == EINPROGRESS || error == EALREADY || error == EINTR || Self.wouldBlock(error) {
            channel.watchWrite { [weak self] in self?.finishRelayConnect() }
        } else {
            fail(Self.socketError("Connect UDP relay", error))
        }
    }

    private func finishRelayConnect() {
        guard phase == .relayConnecting, let channel = udp else { return }
        guard admission.permits(generation) else { stop(); return }
        var error: Int32 = 0
        var length = socklen_t(MemoryLayout<Int32>.size)
        guard getsockopt(channel.fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 else {
            fail(Self.socketError("Inspect UDP connection", errno)); return
        }
        guard error == 0 else { fail(Self.socketError("Connect UDP relay", error)); return }
        guard let actual = Self.address(channel.fd, peer: true) else {
            fail(Self.socketError("Read UDP relay endpoint", errno)); return
        }
        udpPeer = actual
        input.removeAll(keepingCapacity: false)
        phase = .ready
        setupDeadline = nil
        channel.unwatchWrite()
        channel.watchRead { [weak self] in self?.readUDP() }
        onEvent(.ready)
    }

    private func waitForUDPWrite() -> SendResult {
        udp?.watchWrite { [weak self] in
            guard let self, self.phase == .ready else { return }
            self.udp?.unwatchWrite()
            self.onEvent(.writable)
        }
        return .blocked
    }

    private func readUDP() {
        guard phase == .ready, let channel = udp, let peer = udpPeer else { return }
        guard admission.permits(generation) else { stop(); return }
        var errors = 0
        for _ in 0..<64 {
            let consumed = receiveBuffer.withUnsafeMutableBytes {
                recv(channel.fd, $0.baseAddress!, $0.count, 0)
            }
            if consumed >= 0 {
                if consumed > 0 { observe(peer, consumed, false) }
                // The connected socket admits only the relay peer. This
                // application's receive contract is consume-only: valid,
                // malformed, fragmented and empty replies all have no further
                // action. Parsing unused payloads would add no validation
                // boundary and must not create response tracking or timers.
                continue
            }
            let error = errno
            if error == EINTR { continue }
            if Self.wouldBlock(error) { return }
            if error == EBADF || error == ENOTSOCK || error == ENOTCONN {
                fail(Self.socketError("Read SOCKS5 UDP", error))
                return
            }
            // A datagram error can precede already queued data. Try once more
            // without turning a persistent socket error into a busy loop.
            errors += 1
            if errors == 2 { return }
        }
        guard !receiveContinuation else { return }
        receiveContinuation = true
        queue.async { [weak self] in
            guard let self else { return }
            self.receiveContinuation = false
            self.readUDP()
        }
    }

    private func fail(_ message: String) {
        guard phase != .closed else { return }
        stop()
        onEvent(.failed(message))
    }
    private static func wouldBlock(_ code: Int32) -> Bool { code == EAGAIN || code == EWOULDBLOCK }
    private static func socketError(_ operation: String, _ code: Int32) -> String {
        operation + ": " + String(cString: strerror(code))
    }
    private static func address(_ fd: Int32, peer: Bool) -> Address? {
        var storage = sockaddr_storage()
        var length = socklen_t(MemoryLayout<sockaddr_storage>.size)
        return withUnsafeMutablePointer(to: &storage) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                let result = peer ? getpeername(fd, $0, &length) : getsockname(fd, $0, &length)
                return result == 0 ? Address($0, length: length) : nil
            }
        }
    }
    private static func makeSocket(family: Int32, stream: Bool) -> Int32 {
        #if canImport(Darwin)
        let kind = stream ? SOCK_STREAM : SOCK_DGRAM
        #else
        let kind = Int32((stream ? SOCK_STREAM : SOCK_DGRAM).rawValue)
        #endif
        let fd = socket(family, kind, 0)
        guard fd >= 0 else { return -1 }
        let flags = fcntl(fd, F_GETFL, 0)
        let descriptorFlags = fcntl(fd, F_GETFD, 0)
        guard flags >= 0, descriptorFlags >= 0,
              fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0,
              fcntl(fd, F_SETFD, descriptorFlags | FD_CLOEXEC) == 0 else {
            let error = errno
            closeSocket(fd)
            errno = error
            return -1
        }
        #if canImport(Darwin)
        var enabled: Int32 = 1
        if stream && setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled,
                               socklen_t(MemoryLayout<Int32>.size)) != 0 {
            let error = errno
            closeSocket(fd)
            errno = error
            return -1
        }
        #endif
        return fd
    }
    private static func writeSocket(_ fd: Int32, _ bytes: UnsafeRawPointer, _ count: Int) -> Int {
        #if canImport(Darwin)
        return Darwin.send(fd, bytes, count, 0)
        #else
        return Glibc.send(fd, bytes, count, Int32(MSG_NOSIGNAL))
        #endif
    }
    private static func closeSocket(_ fd: Int32) {
        #if canImport(Darwin)
        _ = Darwin.close(fd)
        #else
        _ = Glibc.close(fd)
        #endif
    }

    /// Each source keeps the descriptor alive until its cancellation handler.
    /// Removing write interest never leaves a suspended source or closes an fd
    /// still owned by another queued handler.
    private final class Channel: @unchecked Sendable {
        let fd: Int32
        private let queue: DispatchQueue
        private var reader: DispatchSourceRead?
        private var writer: DispatchSourceWrite?
        private var sources = 0
        private var closing = false
        private var closed = false
        init(fd: Int32, queue: DispatchQueue) { self.fd = fd; self.queue = queue }
        func watchRead(_ handler: @escaping @Sendable () -> Void) {
            guard !closing else { return }
            if let reader { reader.setEventHandler(handler: handler); return }
            let source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
            reader = source
            sources += 1
            source.setEventHandler(handler: handler)
            source.setCancelHandler { [self] in released() }
            source.resume()
        }
        func watchWrite(_ handler: @escaping @Sendable () -> Void) {
            guard !closing else { return }
            if let writer { writer.setEventHandler(handler: handler); return }
            let source = DispatchSource.makeWriteSource(fileDescriptor: fd, queue: queue)
            writer = source
            sources += 1
            source.setEventHandler(handler: handler)
            source.setCancelHandler { [self] in released() }
            source.resume()
        }
        func unwatchRead() { reader?.cancel(); reader = nil }
        func unwatchWrite() { writer?.cancel(); writer = nil }
        func close() {
            guard !closing else { return }
            closing = true
            unwatchRead()
            unwatchWrite()
            finishClose()
        }
        private func released() { sources -= 1; finishClose() }
        private func finishClose() {
            if closing && sources == 0 && !closed {
                closed = true
                Socks5UDPClient.closeSocket(fd)
            }
        }
    }

    /// getaddrinfo cannot be cancelled. Bound it process-wide to one active
    /// request and the latest pending request; obsolete completions are ignored.
    private final class RelayResolver: @unchecked Sendable {
        static let shared = RelayResolver()
        private struct Request: Sendable {
            let host: String
            let port: UInt16
            let family: Int32
            let queue: DispatchQueue
            let completion: @Sendable (Address?) -> Void
        }
        private let lock = NSLock()
        private var busy = false
        private var pending: Request?
        func resolve(_ host: String, port: UInt16, family: Int32, queue: DispatchQueue,
                     completion: @escaping @Sendable (Address?) -> Void) {
            let request = Request(host: host, port: port, family: family, queue: queue, completion: completion)
            lock.lock()
            if busy {
                pending = request
                lock.unlock()
            } else {
                busy = true
                lock.unlock()
                run(request)
            }
        }
        private func run(_ request: Request) {
            DispatchQueue.global(qos: .utility).async { [self] in
                var hints = addrinfo()
                hints.ai_family = request.family
                #if canImport(Darwin)
                hints.ai_socktype = SOCK_DGRAM
                #else
                hints.ai_socktype = Int32(SOCK_DGRAM.rawValue)
                #endif
                hints.ai_protocol = Int32(IPPROTO_UDP)
                var list: UnsafeMutablePointer<addrinfo>?
                let result = request.host.withCString { host in
                    String(request.port).withCString { getaddrinfo(host, $0, &hints, &list) }
                }
                var address: Address?
                if result == 0, let first = list {
                    if let raw = first.pointee.ai_addr {
                        address = Address(raw, length: first.pointee.ai_addrlen)
                    }
                    freeaddrinfo(first)
                }
                let resolved = address
                request.queue.async { request.completion(resolved) }
                lock.lock()
                let next = pending
                pending = nil
                busy = next != nil
                lock.unlock()
                if let next { run(next) }
            }
        }
    }
}
