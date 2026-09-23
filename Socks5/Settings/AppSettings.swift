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
        let data = try encoder.encode(self)
        guard data.count <= 65_536 else { throw SettingsError.invalid("Settings file exceeds 64 KB.") }
        return data
    }

    static func decoded(_ data: Data) throws -> Self {
        guard data.count <= 65_536 else { throw SettingsError.invalid("Settings file exceeds 64 KB.") }
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
