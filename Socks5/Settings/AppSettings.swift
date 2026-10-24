import Foundation

/// The complete, portable configuration. Runtime counters and errors are not settings.
struct AppSettings: Codable, Equatable, Sendable {
    enum Tab: String, Codable, Sendable { case statistics, server, background, settings }
    struct Background: Codable, Equatable, Sendable {
        var continuousLocation = false
        var silentAudio = false
        struct PeriodicPing: Codable, Equatable, Sendable {
            var enabled = false
            var destinations = "1.1.1.1"
            var period = "1000"
        }
        var periodicPing = PeriodicPing()

        init(continuousLocation: Bool = false, silentAudio: Bool = false,
             periodicPing: PeriodicPing = PeriodicPing()) {
            self.continuousLocation = continuousLocation
            self.silentAudio = silentAudio
            self.periodicPing = periodicPing
        }
        private enum CodingKeys: String, CodingKey { case continuousLocation, silentAudio, periodicPing }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            continuousLocation = try values.decode(Bool.self, forKey: .continuousLocation)
            silentAudio = try values.decode(Bool.self, forKey: .silentAudio)
            // Existing version-1 backups have no ping field. Missing means defaults;
            // an explicitly malformed/null field is not silently discarded.
            periodicPing = try values.contains(.periodicPing)
                ? values.decode(PeriodicPing.self, forKey: .periodicPing) : PeriodicPing()
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
