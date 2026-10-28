import Foundation

/// The complete, portable configuration. Runtime counters and errors are not settings.
struct AppSettings: Codable, Equatable, Sendable {
    enum Tab: String, Codable, Sendable { case statistics, server, background, settings }
    struct Background: Codable, Equatable, Sendable {
        struct UDPEcho: Codable, Equatable, Sendable {
            var enabled = false
            var destinations = "1.1.1.1"
            var period = "1000"

            static func == (lhs: Self, rhs: Self) -> Bool {
                lhs.enabled == rhs.enabled &&
                    lhs.destinations.utf8.elementsEqual(rhs.destinations.utf8) &&
                    lhs.period.utf8.elementsEqual(rhs.period.utf8)
            }
        }

        var continuousLocation = false
        var silentAudio = false
        var periodicUDPEcho = UDPEcho()

        private enum CodingKeys: String, CodingKey {
            case continuousLocation, silentAudio, periodicUDPEcho
        }

        init(continuousLocation: Bool = false, silentAudio: Bool = false,
             periodicUDPEcho: UDPEcho = UDPEcho()) {
            self.continuousLocation = continuousLocation
            self.silentAudio = silentAudio
            self.periodicUDPEcho = periodicUDPEcho
        }

        init(from decoder: Decoder) throws {
            let fields = try decoder.container(keyedBy: CodingKeys.self)
            continuousLocation = try fields.decode(Bool.self, forKey: .continuousLocation)
            silentAudio = try fields.decode(Bool.self, forKey: .silentAudio)
            // Only absence supplies defaults. Explicit null and incomplete
            // objects are invalid; unknown historical fields remain inert.
            periodicUDPEcho = fields.contains(.periodicUDPEcho) ?
                try fields.decode(UDPEcho.self, forKey: .periodicUDPEcho) : UDPEcho()
        }
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
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.version == 1 else { throw SettingsError.invalid("Unsupported settings version.") }
        return value
    }
}

enum SettingsError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}
