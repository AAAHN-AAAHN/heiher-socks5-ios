import Foundation

struct ServerSettings: Codable, Equatable {
    var workers = "4"
    var listenAddress = "::"
    var listenPort = "1080"
    var udpListenAddress = ""
    var udpListenPort = "1080"
    var bindIPv4Address = "0.0.0.0"
    var bindIPv6Address = "::"
    var bindInterface = ""
    var authUsername = ""
    var authPassword = ""
    var listenIPv6Only = false

    /// Validate before starting; partially edited text can still be saved as a draft.
    func configuration() throws -> String {
        guard let count = Int(workers), (1...64).contains(count),
              let port = Int(listenPort), (1...65535).contains(port),
              let udpPort = Int(udpListenPort), (0...65535).contains(udpPort) else {
            throw ServerConfigurationError.invalid("Use 1-64 workers, a listen port of 1-65535, and a UDP port of 0-65535.")
        }
        let fields = [listenAddress, udpListenAddress, bindIPv4Address, bindIPv6Address,
                      bindInterface, authUsername, authPassword]
        // The native parser stores each of these fields in a 256-byte C buffer.
        guard fields.allSatisfy({ $0.utf8.count <= 255 && $0.rangeOfCharacter(from: .controlCharacters.union(.newlines)) == nil }),
              authUsername.isEmpty == authPassword.isEmpty else {
            throw ServerConfigurationError.invalid("Text fields must be single-line and at most 255 UTF-8 bytes. Set both authentication fields or leave both empty.")
        }
        func quote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "''") + "'" }
        return """
        main:
          workers: \(count)
          port: \(port)
          listen-address: \(quote(listenAddress))
          udp-port: \(udpPort)
          udp-listen-address: \(quote(udpListenAddress))
          listen-ipv6-only: \(listenIPv6Only)
          bind-address-v4: \(quote(bindIPv4Address))
          bind-address-v6: \(quote(bindIPv6Address))
          bind-interface: \(quote(bindInterface))
        auth:
          username: \(quote(authUsername))
          password: \(quote(authPassword))
        """
    }
}

enum ServerConfigurationError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}
