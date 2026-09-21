import Foundation

/// The complete, portable configuration. Runtime counters and errors are not settings.
struct AppSettings: Codable, Equatable {
    enum Tab: String, Codable { case statistics, server, background, settings }
    struct Background: Codable, Equatable {
        var continuousLocation = false
        var silentAudio = false
    }

    var version = 1
    var server = ServerSettings()
    var serverRunning = false
    var background = Background()
    var selectedTab = Tab.statistics

    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(self)
    }

    static func decoded(_ data: Data) throws -> Self {
        guard data.count <= 65_536 else { throw SettingsError.invalid("Settings file exceeds 64 KB.") }
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.version == 1 else { throw SettingsError.invalid("Unsupported settings version.") }
        return value
    }
}

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
            throw SettingsError.invalid("Use 1-64 workers, a listen port of 1-65535, and a UDP port of 0-65535.")
        }
        let fields = [listenAddress, udpListenAddress, bindIPv4Address, bindIPv6Address,
                      bindInterface, authUsername, authPassword]
        guard fields.allSatisfy({ $0.utf8.count <= 1024 && $0.rangeOfCharacter(from: .controlCharacters) == nil }),
              authUsername.utf8.count <= 255, authPassword.utf8.count <= 255,
              authUsername.isEmpty == authPassword.isEmpty else {
            throw SettingsError.invalid("Address fields must be single-line. Set both authentication fields or leave both empty (255 UTF-8 bytes each maximum).")
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

enum SettingsError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}
